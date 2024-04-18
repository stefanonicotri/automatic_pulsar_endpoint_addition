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
users_json = users.json()
user_ids = [ users_json[i]["id"] for i in range(len(users_json)) ]

user_preferences = {}

for id in user_ids:
    user_preference = requests.get(base_url + "/users/" + id, params = my_auth_params)
    user_preference_json = user_preference.json()
    user_preferences[id] = user_preference_json["preferences"];


# """ 
# Filter the user_preferences dictionary keeping only items containing the extra_user_preferences dictionary in the values. 
# The result is a subdictionary of user_preferences (and is still a dictionary)
# """
# filtered_user_preferences = {key: value for key, value in user_preferences.items() if isinstance(value, dict) and 'extra_user_preferences' in value}

""" 
This is to filter the user_preferences dictionary keeping **in an array** only the values of the dictionary items containing the extra_user_preferences dictionary
"""
def filter_extra_preferences(user_preferences_dictionary):
  """
  Filters a dictionary and extracts values of 'extra_user_preferences' dictionaries.

  Args:
      user_preferences_dictionary: A dictionary containing user preferences.

  Returns:
      A list containing only the values of the 'extra_user_preferences' dictionaries.
  """

  extra_preferences = []
  for value in user_preferences_dictionary.values():
    # Check if value is a dictionary and has the key 'extra_user_preferences'
    if isinstance(value, dict) and 'extra_user_preferences' in value:
      # Extract the value of the 'extra_user_preferences' key
      extra_preferences.append(value['extra_user_preferences'])
  return extra_preferences

extracted_extra_preferences = [ json.loads(item) for item in filter_extra_preferences(user_preferences) ]

# Extract informations to be put in the pull request
extracted_distributed_compute = [item['distributed_compute|remote_resources'] for item in extracted_extra_preferences]

"""
This is to extract information from the infrastructure playbook repository
"""

# Get the URL of the infrastructure playbook repository from the variables in the .env file
#repo_url = os.getenv("REPO_URL")

repo = Repo(config["repo_local_dir"])
repo.remotes.origin.pull()

# Load user preferences extra conf from the corresponding repo yaml file
repo_user_preferences_extra_conf_file = os.path.join(config["repo_local_dir"], config["repo_user_preferences_extra_conf"])
with open(repo_user_preferences_extra_conf_file, 'r') as file:
    repo_user_preferences_extra_conf_yaml = yaml.safe_load(file)

# add stuff to repo_user_preferences_extra_conf_yaml["preferences"]["distributed_compute"]["inputs"][0]["options"]

# Load destinations from the corresponding repo yaml file
repo_destinations_file = os.path.join(config["repo_local_dir"], config["repo_destinations"])
with open(repo_destinations_file, 'r') as file:
    repo_destinations_yaml = yaml.safe_load(file)

# add stuff to repo_destinations_yaml["destinations"]

# Load MQ settings from the corresponding repo yaml file
repo_mq_file = os.path.join(config["repo_local_dir"], config["repo_mq"])
with open(repo_mq_file, 'r') as file:
    repo_mq_yaml = yaml.safe_load(file)

# Load Pulsar secrets from the corresponding repo yaml file
repo_pulsar_secrets_file = os.path.join(config["repo_local_dir"], config["repo_pulsar_secrets"])
with open(repo_pulsar_secrets_file, 'r') as file:
    repo_pulsar_secrets_yaml = yaml.safe_load(file)

# Load job conf from the corresponding repo yaml file
repo_job_conf_file = os.path.join(config["repo_local_dir"], config["repo_job_conf"])
with open(repo_job_conf_file, 'r') as file:
    repo_job_conf_yaml = yaml.safe_load(file)


"""
This is to generate a random password
"""
#generated_password = ''.join(random.choice(string.printable) for i in range(14))
characters_pool = string.ascii_letters + string.digits + string.punctuation
generated_password = ''.join(random.choice(characters_pool) for i in range(14))
