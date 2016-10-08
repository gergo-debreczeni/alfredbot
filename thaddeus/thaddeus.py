from __future__ import print_function
import base64
import logging

import boto3
from pymemcache.client.hash import HashClient
from pynamodb.attributes import NumberAttribute, UnicodeAttribute
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection
from pynamodb.models import Model
from slacker import Slacker

log = logging.getLogger()
log.setLevel(logging.INFO)

MEMCACHED_ENDPOINT = 'alfredbot-users.atjtz9.cfg.euw1.cache.amazonaws.com'
MEMCACHED_PORT = 11211
KMS_ALIAS = 'alias/alfredbot-token'
CONFIG_TABLE_NAME = 'alfredbot-configuration'
TOKEN_TABLE_NAME = 'alfredbot-token'
REGION = 'eu-west-1'


class MemCacheHelper(object):
    def __init__(self):
        self.client = HashClient([
            (MEMCACHED_ENDPOINT, MEMCACHED_PORT)
        ])

    def set(self, key, value):
        self.client.set(key, value)

    def get(self, key):
        return self.client.get(key)


class ViewIndex(GlobalSecondaryIndex):
    class Meta:
        read_capacity_units = 1
        write_capacity_units = 1
        index_name = 'team_id-index'
        projection = AllProjection()

    team_id = UnicodeAttribute(hash_key=True)


class TeamConfigModel(Model):
    class Meta:
        table_name = CONFIG_TABLE_NAME
        region = REGION

    id = UnicodeAttribute(hash_key=True)
    team_id_index = ViewIndex()
    friendly_name = UnicodeAttribute()
    team_id = UnicodeAttribute()
    type = UnicodeAttribute()
    arn = UnicodeAttribute()
    priority = NumberAttribute()


class TeamModel(Model):
    class Meta:
        table_name = TOKEN_TABLE_NAME
        region = REGION

    team_id = UnicodeAttribute(hash_key=True)
    token = UnicodeAttribute()


def get_team_config(team_id):
    team_configs = TeamConfigModel.team_id_index.query(team_id)
    return list(team_configs)


def decrypt(cipher_text):
    kms = boto3.client('kms')
    res = kms.decrypt(CiphertextBlob=base64.b64decode(cipher_text))
    return res.get('Plaintext')


def get_token(team_id):
    for team in TeamModel.query(team_id):
        token = decrypt(team.token)
        return token


def get_config(configs, id):
    for config in configs:
        if config.id == id:
            return config


def add_to_cache(team_id, user, role):
    # Need to concatenate team_id and user as user is only unique within the team
    mc = MemCacheHelper()
    unique_user_id = '%s_%s' % (team_id, user)
    mc.set(unique_user_id, role)
    log.info('Value in memcached for %s is %s' % (unique_user_id, mc.get(unique_user_id)))


def parse(team_id, division, team_config):
    # Treat channel/group/usergroup as one type because the field structure of interest is the same
    configured_ids = [config.id for config in team_config]
    users = {}
    for subdivision in division:
        if subdivision['id'] in configured_ids:
            config = get_config(team_config, subdivision['id'])
            for user in subdivision['members']:
                if user in users.keys():
                    users[user].append(config)
                else:
                    users[user] = [config]

    for user, configs in users.iteritems():
        # Find out which role weights the most.
        # In case user belongs to several channels with different roles, we want the strongest one.
        config = min(configs, key=lambda x: x.priority)
        add_to_cache(team_id, user, config.arn)


def update_role_mapping(team_id):
    token = get_token(team_id)
    slack = Slacker(token)
    groups = slack.groups.list().body['groups']
    channels = slack.channels.list().body['channels']
    usergroups = slack.usergroups.list().body['usergroups']
    division = groups + channels + usergroups
    team_config = get_team_config(team_id)
    parse(team_id, division, team_config)


def handler(event, context):
    try:
        log.debug(event)
        team_id = event['team_id']
        update_role_mapping(team_id)
        message = 'Sync successful.'
    except Exception as e:
        log.exception(e)
        message = e.message
    return {
        "response_type": "in_channel",
        'text': message
    }
