import json
import argparse
from urllib.parse import urljoin
import requests
from git import Repo
import os
import yaml
import random
import string
from ansible_vault import Vault

# Parse CLI args
parser = argparse.ArgumentParser()
parser.add_argument('--dry-run', action='store_true', help='Run script without making any changes')
args = parser.parse_args()

# Load config from config.json
with open('config.json', 'r') as f:
  config = json.load(f)

# Load secrets from secrets.json
with open('secrets.json', 'r') as f:
  secrets = json.load(f)

# Set Galaxy server URL from config and API key from secrets
base_url = urljoin(config["server_url"], '/api')
my_auth_params = { 'key': secrets["api_key"] }
my_users_params = { 'deleted': 'false' }

users = requests.get(base_url + "/users", params = dict(**my_users_params, **my_auth_params))
if users.status_code != 200:
    raise Exception(f"Request failed with status code {users.status_code}: {users.text}")

users_json = users.json()
active_users = [
    {k: v for k, v in user.items() if k in ['id', 'username']}
    for user in users_json if not user['deleted'] and user['active']
]

active_user_ids = [user['id'] for user in active_users]

for id in active_user_ids:
    user = requests.get(base_url + "/users/" + id, params=my_auth_params).json()
    next((u.update({'preferences': user['preferences']}) for u in active_users if u['id'] == id), None)

active_users_with_extra_preferences = [
    user for user in active_users if 'extra_user_preferences' in user['preferences']
]

active_users_with_byoc_pulsar = []
for user in active_users_with_extra_preferences:
    if 'byoc_pulsar|' in user['preferences']['extra_user_preferences']:
        extra_prefs = json.loads(user['preferences']['extra_user_preferences'])
        byoc_pulsar_prefs = {k: v for k, v in extra_prefs.items() if k.startswith("byoc_pulsar|")}
        user.update(byoc_pulsar_prefs)
        del user['preferences']
        active_users_with_byoc_pulsar.append(user)

repo = Repo(config["repo_local_dir"])
repo.remotes.origin.pull()

# DESTINATIONS
repo_destinations_file = os.path.join(config["repo_local_dir"], config["repo_destinations"])
with open(repo_destinations_file, 'r') as file:
    repo_destinations_yaml = yaml.safe_load(file)

for user in active_users_with_byoc_pulsar:
    key = f"pulsar_{user['username']}_tpv"
    if key not in repo_destinations_yaml["destinations"]:
        repo_destinations_yaml["destinations"][key] = {
            "inherits": "pulsar_default",
            "runner": f"pulsar_{user['username']}_runner",
            "max_accepted_cores": user["byoc_pulsar|max_accepted_cores"],
            "max_accepted_mem": user["byoc_pulsar|max_accepted_mem"],
            "min_accepted_gpus": user["byoc_pulsar|min_accepted_gpus"],
            "max_accepted_gpus": user["byoc_pulsar|max_accepted_gpus"],
            "scheduling": {"require": [f"{user['username']}-pulsar"]}
        };

if not args.dry_run:
    with open(repo_destinations_file, 'w') as file:
        yaml.dump(repo_destinations_yaml, file)
else:
    print(f"[DRY-RUN] Would write updated destinations to {repo_destinations_file}")

# RABBITMQ
repo_mq_file = os.path.join(config["repo_local_dir"], config["repo_mq"])
with open(repo_mq_file, 'r') as file:
    repo_mq_yaml = yaml.safe_load(file)

for user in active_users_with_byoc_pulsar:
    if not any(r['user'] == f"galaxy_{user['byoc_pulsar|username']}" for r in repo_mq_yaml["rabbitmq_users"]):
        repo_mq_yaml["rabbitmq_users"].append({
            'password': f"{{{{ rabbitmq_password_galaxy_{user['byoc_pulsar|username']} }}}}",
            'user': f"galaxy_{user['byoc_pulsar|username']}",
            'vhost': f"/pulsar/galaxy_{user['byoc_pulsar|username']}"
        });

if not args.dry_run:
    with open(repo_mq_file, 'w') as file:
        yaml.dump(repo_mq_yaml, file)
else:
    print(f"[DRY-RUN] Would write updated MQ config to {repo_mq_file}")

# JOB_CONF
repo_job_conf_file = os.path.join(config["repo_local_dir"], config["repo_job_conf"])
with open(repo_job_conf_file, 'r') as file:
    repo_job_conf_yaml = yaml.safe_load(file)

for user in active_users_with_byoc_pulsar:
    plugin_id = f"pulsar_eu_{user['byoc_pulsar|username']}"
    if not any(p['id'] == plugin_id for p in repo_job_conf_yaml["galaxy_jobconf"]["plugins"]):
        repo_job_conf_yaml["galaxy_jobconf"]["plugins"].append({
            'id': plugin_id,
            'load': 'galaxy.jobs.runners.pulsar:PulsarMQJobRunner',
            'params': {
                'amqp_url': f"pyamqp://galaxy_{user['byoc_pulsar|username']}:{{{{ rabbitmq_password_galaxy_{user['byoc_pulsar|username']} }}}}@mq.galaxyproject.eu:5671//pulsar/galaxy_{user['byoc_pulsar|username']}?ssl=1",
                'galaxy_url': "https://usegalaxy.eu",
                'manager': 'production',
                'amqp_acknowledge': "true",
                'amqp_ack_republish_time': 300,
                'amqp_consumer_timeout': 2.0,
                'amqp_publish_retry': "true",
                'amqp_publish_retry_max_retries': 60
            }
        })

if not args.dry_run:
    with open(repo_job_conf_file, 'w') as file:
        yaml.dump(repo_job_conf_yaml, file, default_flow_style=False, width=float("inf"))
else:
    print(f"[DRY-RUN] Would write updated job conf to {repo_job_conf_file}")

# RABBITMQ PASSWORD
characters_pool = string.ascii_letters + string.digits
for user in active_users_with_byoc_pulsar:
    if not user.get('byoc_pulsar|password'):
        user['byoc_pulsar|password'] = ''.join(random.choice(characters_pool) for _ in range(14))

repo_pulsar_secrets_file = os.path.join(config["repo_local_dir"], config["repo_pulsar_secrets"])
vault = Vault(secrets["vault_password"])
with open(repo_pulsar_secrets_file, 'r') as file:
    encrypted_data = file.read()

try:
    pulsar_secrets = vault.load(encrypted_data)
except Exception as e:
    raise Exception("Decryption failed: " + str(e))

for user in active_users_with_byoc_pulsar:
    key = f"rabbitmq_password_galaxy_{user['byoc_pulsar|username']}"
    if key not in pulsar_secrets:
        pulsar_secrets[key] = user["byoc_pulsar|password"]

encrypted_data = vault.dump(pulsar_secrets)

if not args.dry_run:
    with open(repo_pulsar_secrets_file, 'w') as file:
        file.write(encrypted_data)
else:
    print(f"[DRY-RUN] Would write updated encrypted secrets to {repo_pulsar_secrets_file}")

if not args.dry_run:
    repo.index.add([repo_destinations_file, repo_mq_file, repo_job_conf_file, repo_pulsar_secrets_file])
    repo.index.commit("Update Pulsar configurations for active users with BYOC Pulsar preferences")
    repo.remote(name='origin').push()
else:
    print("[DRY-RUN] Would commit and push the changes to the repository")

pr_data = {
    "title": "Update Pulsar configurations for active users with BYOC Pulsar preferences",
    "body": "This pull request updates the Pulsar configurations for active users with BYOC Pulsar preferences.",
    "head": config["branch_name"],
    "base": "main"
}

if not args.dry_run:
    response = requests.post(
        urljoin(config["repo_api_url"], '/pulls'),
        headers={'Authorization': f'token {secrets["github_token"]}'},
        json=pr_data
    )
    if response.status_code != 201:
        raise Exception(f"Pull request creation failed with status code {response.status_code}: {response.text}")
    print("Pull request created successfully.")
else:
    print("[DRY-RUN] Would create pull request with the following data:")
    print(json.dumps(pr_data, indent=2))
