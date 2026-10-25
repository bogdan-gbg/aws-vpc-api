"""Print a Cognito access token for one of the test users.

Uses the "cli" app client and ADMIN_USER_PASSWORD_AUTH, which needs the operator's
AWS credentials in addition to the password. The token is never written to disk.

    $env:TOKEN = python scripts/get_token.py --user demo-owner
"""

import argparse

import boto3

from tf_outputs import load_outputs

USERS = {
    "demo-owner": ("demo_owner_username", "demo_owner_password"),
    "reviewer": ("reviewer_username", "reviewer_password"),
}


def get_access_token(user: str) -> str:
    username_output, password_output = USERS[user]
    outputs = load_outputs()
    user_pool_id = str(outputs["user_pool_id"])
    # A user pool id is "<region>_<id>".
    region = user_pool_id.split("_", 1)[0]
    client = boto3.client("cognito-idp", region_name=region)
    result = client.admin_initiate_auth(
        UserPoolId=user_pool_id,
        ClientId=str(outputs["cli_client_id"]),
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": str(outputs[username_output]),
            "PASSWORD": str(outputs[password_output]),
        },
    )
    if "AuthenticationResult" not in result:
        raise RuntimeError(f"Unexpected Cognito challenge: {result.get('ChallengeName')}")
    return result["AuthenticationResult"]["AccessToken"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", choices=sorted(USERS), default="demo-owner")
    args = parser.parse_args()
    # Only the token on stdout, so it can be captured in a variable.
    print(get_access_token(args.user))


if __name__ == "__main__":
    main()
