import base64
import json
import logging

import boto3
from pynamodb.models import Model
from pynamodb.attributes import UnicodeAttribute
from slacker import Slacker

log = logging.getLogger()
log.setLevel(logging.DEBUG)

BUCKET_NAME = 'alfredbot-configuration'
OBJECT_NAME = 'credentials.json'
KMS_ALIAS = 'alias/alfredbot-token'
TABLE_NAME = 'alfredbot-token'
REGION = 'eu-west-1'


class TeamModel(Model):
    class Meta:
        table_name = TABLE_NAME
        region = REGION
    team_id = UnicodeAttribute(hash_key=True)
    token = UnicodeAttribute()


def save_token(team_id, encrypted_token):
    team = TeamModel(team_id=team_id,
                     token=encrypted_token)
    team.save()

def encrypt(token):
    kms = boto3.client('kms')
    c_text = kms.encrypt(KeyId=KMS_ALIAS, Plaintext=token)
    return base64.b64encode(c_text['CiphertextBlob'])

def load_credentials():
    # TODO(@gdebreczeni): encrypt client id and secret
    s3 = boto3.resource('s3')
    object = s3.Object(BUCKET_NAME, OBJECT_NAME)
    body = object.get()['Body']
    credentials = json.loads(body.read())
    return credentials

def authorise(code):
    slack = Slacker('mock')
    credentials = load_credentials()
    response = slack.oauth.access(client_id=credentials['client_id'],
                                  client_secret=credentials['client_secret'],
                                  code=code)
    auth_body = response.body
    return auth_body

def handler(event, context):
    try:
        print event
        code = event['params']['querystring']['code']
        auth_body = authorise(code)
        team_id = auth_body['team_id']
        token = auth_body['access_token']
        encrypted_token = encrypt(token)
        save_token(team_id, encrypted_token)
        log.info('Saved token for team %s' % team_id)
    except Exception as e:
        print e
        log.exception(e)
        return {'location': 'http://alfredbot.io/error.html'}
    return {'location': 'http://alfredbot.io/'}
