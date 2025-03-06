# Automatic addition of Pulsar endpoint

This script fetches information from a Galaxy instance needed for the addition of a Pulsar endpoints and formats it in the relevant pull request, then submits it.

## Requirements
Install required libraries with `python -m pip install -r requirements.txt`

In order to be run, the script needs two files:

1. file `config.json` with the following content:
    ```
    {
        "server_url": <URL_OF_GALAXY_SERVER>,
        "repo_url": <URL_OF_REP_FOR_PULL_REQUEST>,
        "repo_local_dir": <LOCAL_PATH_OF_PULLED_REPO>,
        "repo_user_preferences_extra_conf": <LOCAL_PATH_OF_EXTRA_CONF_FILE_IN_REPO>,
        "repo_destinations": <LOCAL_PATH_OF_DESTINATIONS_FILE_IN_REPO>,
        "repo_mq": <LOCAL_PATH_OF_MQ_CONF_FILE_IN_REPO>,,
        "repo_pulsar_secrets": <LOCAL_PATH_OF_MQ_PASSWORD_FILE_IN_REPO>,,
        "repo_job_conf": <LOCAL_PATH_OF_JOB_CONF_FILE_IN_REPO>,
    }
    ```
2. file `secrets.json` with the following content:
    ```
    {
        "api_key": <API_KEY_FOR_ADMIN_ACCESS_TO_GALAXY>,
        "vault_password": <ANSIBLE_VAULT_PASSWORD_USED_TO_ENCRYPT_MQ_PASSWORD_FILE_IN_REPO>
    }
    ```
## Execution

Execute the script with `python main.py`.