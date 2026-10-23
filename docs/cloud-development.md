# Develop from ChatGPT on iPhone

1. On web or desktop, create a Codex Cloud environment and select `leodoin/garmin-connect`. Authorize repository access if requested.
2. Set setup command to `bash scripts/cloud-setup.sh`. The environment needs package download access during setup. It does not need Garmin credentials, an OpenAI runtime key, SSH keys, or GCP credentials.
3. Run setup and verify tests, then publish the environment.
4. On iPhone, open Codex in ChatGPT, choose Cloud and the published environment, and describe a change. Review the diff and tests, then commit or open a pull request.
5. Deployment to the existing GCP service is separate. Merging code alone does not update the service.

Suggested request: “Add a read-only Garmin metric to get_health_history. Follow AGENTS.md, add regression coverage, run tests, and open a pull request. Do not change production.”

If the environment or Codex Cloud option is absent, check plan/workspace availability. Merely connecting GitHub to ordinary ChatGPT does not create a coding environment.

Official documentation: https://learn.chatgpt.com/docs/environments/cloud-environments
