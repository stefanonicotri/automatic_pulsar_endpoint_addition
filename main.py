import json
from urllib.parse import urljoin
import requests
from git import Repo
import os
import yaml
import random
import string
from ansible_vault import Vault


# Load config from config.json
with open('config.json', 'r') as f:
  config = json.load(f)

# Load secrets from secrets.json
with open('secrets.json', 'r') as f:
  secrets = json.load(f)

# Set Galaxy server URL from config (config.json) and API key from secrets (secrets.json)
base_url = urljoin(config["server_url"], '/api')
my_auth_params = { 'key': secrets["api_key"] }
my_users_params = { 'deleted': 'false' }
""" 
params contains the parameters passed after ? in the url
the request is: curl 'https://$SERVER_URL/api/users?deleted=false&key=$API_KEY'
"""
users = requests.get(base_url + "/users", params = dict(**my_users_params, **my_auth_params))

# Check the status code
if users.status_code != 200:
    raise Exception(f"Request failed with status code {users.status_code}: {users.text}")

users_json = users.json()
user_ids = [ users_json[i]["id"] for i in range(len(users_json)) ]

# the following filters the users_json list keeping only the active users
active_users = [ user for user in users_json if user['deleted'] == False and user['active'] == True ]

# the following removes everything but id and username from the active_users list
active_users = [{k: v for k, v in user.items() if k in ['id', 'username']} for user in active_users]

# the followind extracts a list of user ids from the active_users list
active_user_ids = [ user['id'] for user in active_users ]

# the following extracts the 'preferences' field adding it to the active_users list
for id in active_user_ids:
    user = requests.get(base_url + "/users/" + id, params = my_auth_params)
    user_json = user.json()
    # this adds the "preferences" field of user_json to the element of active_users with the same id
    next((user.update({'preferences': user_json['preferences']}) for user in active_users if user['id'] == id), None);

# the following filters the active_users list keeping only the users that have the 'extra_user_preferences' key in the preferences dictionary
active_users_with_extra_preferences = [ user for user in active_users if 'extra_user_preferences' in user['preferences'] ]

# the following fiters the active_users_with_extra_preferences list keeping only the users that have the 'byoc_pulsar|*' key in the 'extra_user_preferences' dictionary
active_users_with_byoc_pulsar = [ user for user in active_users_with_extra_preferences if 'byoc_pulsar|' in user['preferences']['extra_user_preferences'] ]

for entry in active_users_with_byoc_pulsar:
    if "preferences" in entry and "extra_user_preferences" in entry["preferences"]:
        extra_prefs = json.loads(entry["preferences"]["extra_user_preferences"])
        # Extract only keys starting with "byoc_pulsar|"
        byoc_pulsar_prefs = {k: v for k, v in extra_prefs.items() if k.startswith("byoc_pulsar|")}
        # Move them to the top-level dictionary
        entry.update(byoc_pulsar_prefs)
        # Remove old preferences structure
        del entry["preferences"];



#This is to extract information from the infrastructure playbook repository

# Get the URL of the infrastructure playbook repository from the variables in the .env file
#repo_url = os.getenv("REPO_URL")

repo = Repo(config["repo_local_dir"])
repo.remotes.origin.pull()

################
# DESTINATIONS #
################

# Load destinations from the corresponding repo yaml file
repo_destinations_file = os.path.join(config["repo_local_dir"], config["repo_destinations"])
with open(repo_destinations_file, 'r') as file:
    repo_destinations_yaml = yaml.safe_load(file)

# Check if there is a corresponding entry pulsar_username_tpv in repo_destinations_yaml["destinations"], if not add it
for user in active_users_with_byoc_pulsar:
    pulsar_username_tpv = f"pulsar_{user['username']}_tpv"
    if pulsar_username_tpv not in repo_destinations_yaml["destinations"]:
        # If not, add a new entry
        repo_destinations_yaml["destinations"][pulsar_username_tpv] = {
            "inherits": "pulsar_default",
            "runner": f"pulsar_{user['username']}_runner",
            "max_accepted_cores": user["byoc_pulsar|max_accepted_cores"],
            "max_accepted_mem": user["byoc_pulsar|max_accepted_mem"],
            "min_accepted_gpus": user["byoc_pulsar|min_accepted_gpus"],
            "max_accepted_gpus": user["byoc_pulsar|max_accepted_gpus"],
            "scheduling": {
                "require": [
                    f"{user['username']}-pulsar"
                ]
            }
        };

# Save the updated repo_destinations_yaml to the corresponding repo yaml file
with open(repo_destinations_file, 'w') as file:
    yaml.dump(repo_destinations_yaml, file)

############
# RABBITMQ #
############

# Load MQ settings from the corresponding repo yaml file
repo_mq_file = os.path.join(config["repo_local_dir"], config["repo_mq"])
with open(repo_mq_file, 'r') as file:
    repo_mq_yaml = yaml.safe_load(file)

# Check if there is a corresponding entry in repo_mq_yaml["rabbitmq_users"], if not add it
for user in active_users_with_byoc_pulsar:
    if not any(rabbitmq_user['user'] == f"galaxy_{user['byoc_pulsar|username']}" for rabbitmq_user in repo_mq_yaml["rabbitmq_users"]):
        rabbitmq_user = {
            'password': f"{{{{ rabbitmq_password_galaxy_{user['byoc_pulsar|username']} }}}}",
            'user': f"galaxy_{user['byoc_pulsar|username']}",
            'vhost': f"/pulsar/galaxy_{user['byoc_pulsar|username']}"
        }
        repo_mq_yaml["rabbitmq_users"].append(rabbitmq_user);


# Save the updated repo_mq_yaml to the corresponding repo yaml file
with open(repo_mq_file, 'w') as file:
    yaml.dump(repo_mq_yaml, file)

############
# JOB_CONF #
############

# Load job conf from the corresponding repo yaml file
repo_job_conf_file = os.path.join(config["repo_local_dir"], config["repo_job_conf"])
with open(repo_job_conf_file, 'r') as file:
    repo_job_conf_yaml = yaml.safe_load(file)

# Check if there is a corresponding entry in repo_job_conf_yaml["galaxy_jobconf"]["plugins"], if not add it
for user in active_users_with_byoc_pulsar:
    plugin_id = f"pulsar_eu_{user['byoc_pulsar|username']}"
    if not any(plugin['id'] == plugin_id for plugin in repo_job_conf_yaml["galaxy_jobconf"]["plugins"]):
        new_plugin = {
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
        }
        repo_job_conf_yaml["galaxy_jobconf"]["plugins"].append(new_plugin)

# Save the updated repo_job_conf_yaml to the corresponding repo yaml file
with open(repo_job_conf_file, 'w') as file:
    yaml.dump(repo_job_conf_yaml, file, default_flow_style=False, width=float("inf"))

#####################
# RABBITMQ PASSWORD #
#####################

# generate a strong random password for users who didn't specify one
characters_pool = string.ascii_letters + string.digits # + string.punctuation
for user in active_users_with_byoc_pulsar:
    if not user.get('byoc_pulsar|password'):
        user['byoc_pulsar|password'] = ''.join(random.choice(characters_pool) for i in range(14));

# Load Pulsar secrets from the corresponding repo yaml file
repo_pulsar_secrets_file = os.path.join(config["repo_local_dir"], config["repo_pulsar_secrets"])

# Open the ansible-vault encrypted file repo_pulsar_secrets_file
vault = Vault(secrets["vault_password"])
with open(repo_pulsar_secrets_file, 'r') as file:
    encrypted_data = file.read()

# Decrypt the data
try:
    pulsar_secrets = vault.load(encrypted_data)
except Exception as e:
    raise Exception("Decryption failed: " + str(e))

# Check and add missing entries
for user in active_users_with_byoc_pulsar:
    key = f"rabbitmq_password_galaxy_{user['byoc_pulsar|username']}"
    if key not in pulsar_secrets:
        pulsar_secrets[key] = user["byoc_pulsar|password"];

# Encrypt the data back
encrypted_data = vault.dump(pulsar_secrets);

# Save the updated encrypted data back to the file
with open(repo_pulsar_secrets_file, 'w') as file:
    file.write(encrypted_data)

    # Commit and push changes to the repository
    repo.index.add([repo_destinations_file, repo_mq_file, repo_job_conf_file, repo_pulsar_secrets_file])
    repo.index.commit("Update Pulsar configurations for active users with BYOC Pulsar preferences")
    origin = repo.remote(name='origin')
    origin.push()

    # Create a pull request using the GitHub API
    pr_data = {
        "title": "Update Pulsar configurations for active users with BYOC Pulsar preferences",
        "body": "This pull request updates the Pulsar configurations for active users with BYOC Pulsar preferences.",
        "head": config["branch_name"],
        "base": "main"
    }

    response = requests.post(
        urljoin(config["repo_api_url"], '/pulls'),
        headers={'Authorization': f'token {secrets["github_token"]}'},
        json=pr_data
    )

    if response.status_code != 201:
        raise Exception(f"Pull request creation failed with status code {response.status_code}: {response.text}")

    print("Pull request created successfully.")




# # Load user preferences extra conf from the corresponding repo yaml file
# repo_user_preferences_extra_conf_file = os.path.join(config["repo_local_dir"], config["repo_user_preferences_extra_conf"])
# with open(repo_user_preferences_extra_conf_file, 'r') as file:
#     repo_user_preferences_extra_conf_yaml = yaml.safe_load(file)

# # add stuff to repo_user_preferences_extra_conf_yaml["preferences"]["distributed_compute"]["inputs"][0]["options"]


