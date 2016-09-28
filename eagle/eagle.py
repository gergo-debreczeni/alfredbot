import base64
import logging

import boto3
from pynamodb.attributes import NumberAttribute, UnicodeAttribute
from pynamodb.indexes import GlobalSecondaryIndex, AllProjection
from pynamodb.models import Model
from slacker import Slacker
from tabulate import tabulate

log = logging.getLogger()
log.setLevel(logging.INFO)

KMS_ALIAS = 'alias/alfredbot-token'
CONFIG_TABLE_NAME = 'alfredbot-configuration'
TOKEN_TABLE_NAME = 'alfredbot-token'
REGION = 'eu-west-1'
COMMANDS = ['add', 'remove', 'list', 'help']


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


class SlackHelper(object):
    supported_types = ['group', 'channel', 'usergroup']

    def __init__(self, team_id):
        token = get_token(team_id)
        self.slack = Slacker(token)
        self.commands = {'group': self.get_group,
                         'channel': self.get_channel,
                         'usergroup': self.get_usergroup}
        self.team_id = team_id

    def get_group(self, name):
        groups = self.slack.groups.list().body['groups']
        matches = [g for g in groups if g['name'] == name]
        if matches:
            return matches[0]['id']
        else:
            return False

    def get_channel(self, name):
        channel = self.slack.channels.list().body['channels']
        matches = [cn for cn in channel if cn['name'] == name]
        if matches:
            return matches[0]['id']
        else:
            return False

    def get_usergroup(self, name):
        usergroups = self.slack.usergroups.list().body['usergroups']
        matches = [ug for ug in usergroups if ug['name'] == name]
        if matches:
            return matches[0]['id']
        else:
            return False

    def is_admin(self, user_id):
        user_info = self.slack.users.info(user_id).body
        return user_info['user']['is_admin']

    def get_id(self, mapping_type, type_name):
        id = self.commands[mapping_type](type_name)
        if id:
            return True, id
        else:
            return False, 'No %s with name %s' % (mapping_type, type_name)


def decrypt(cipher_text):
    kms = boto3.client('kms')
    res = kms.decrypt(CiphertextBlob=base64.b64decode(cipher_text))
    return res.get('Plaintext')


def get_token(team_id):
    for team in TeamModel.query(team_id):
        token = decrypt(team.token)
        return token


def save_mapping(team_id, type, friendly_name, type_id, arn, priority):
    team_config = TeamConfigModel(id=type_id,
                                  friendly_name=friendly_name,
                                  team_id=team_id,
                                  type=type,
                                  arn=arn,
                                  priority=priority)
    team_config.save()


def delete_mapping(team_id, type_id):
    team_configs = TeamConfigModel.query(type_id, team_id__eq=team_id)
    for team_config in team_configs:
        team_config.delete()

def add_mapping(sh, args):
    if len(args) != 4:
        message = 'Incorrect number of arguments'
        return False, message
    mapping_type = args[0]
    type_name = args[1]
    arn = args[2]
    priority = int(args[3])
    if mapping_type not in SlackHelper.supported_types:
        message = 'Unsupported mapping type %s\n Accepted values: %s' % \
                  (mapping_type, ' '.join(SlackHelper.supported_types))
        return False, message
    status, _ = sh.get_id(mapping_type, type_name)
    if not status:
        return False, _
    save_mapping(sh.team_id, mapping_type, type_name, _, arn, priority)
    return True, None


def remove_mapping(sh, args):
    if len(args) != 2:
        message = 'Incorrect number of arguments'
        return False, message
    mapping_type = args[0]
    type_name = args[1]
    status, _ = sh.get_id(mapping_type, type_name)
    if not status:
        return False, _
    delete_mapping(sh.team_id, _)
    return True, None


def list_mapping(team_id):
    configs = TeamConfigModel.team_id_index.query(team_id)
    table = []
    for config in configs:
        table.append([config.type, config.friendly_name, config.arn, config.priority])
    tabulated_format = tabulate(table,
                                headers=['Type', 'Friendly Name', 'Arn', 'Priority'],
                                tablefmt='simple')
    return tabulated_format


def bot_help():
    h = "\nUsage: `/alfred-admin <command> <options>`"
    h += "\nAvailable commands `{0}`\n".format(' '.join(COMMANDS))
    h += "\nDetailed command options:"
    h += "\n`/alfred-admin add <type> <name> <role_arn> <priority>`"
    h += "\nCreates new role mapping."
    h += "\nExample: /alfred-admin add channel general arn:aws:iam::account_number:role/readonly 2"
    h += "\n`/alfred-admin remove <type> <name>`"
    h += "\nRemoves role mapping."
    h += "\nExample: /alfred-admin remove channel general"
    h += "\n`/alfred-admin list`"
    h += "\nReturns list of existing role mappings."
    h += "\n For more details see www.alfredbot.io/"
    return h


def handler(event, context):
    try:
        log.info(event)
        raw_text = event['text']
        team_id = event['team_id']
        user_id = event['user_id']
        args = raw_text.split()
        if args[0] not in COMMANDS:
            message = 'Unsuported command %s\n\n' % args[0]
            message += bot_help()
            log.error(message)
        elif args[0] == 'help':
            message = bot_help()
        elif args[0] == 'list':
            message = list_mapping(team_id)
            log.info(message)
        else:
            sh = SlackHelper(team_id)
            if sh.is_admin(user_id):
                if args[0] == 'add':
                    status, message = add_mapping(sh, args[1:])
                    if status:
                        message = list_mapping(team_id)
                        log.info(message)
                    else:
                        log.error(message)
                elif args[0] == 'remove':
                    status, message = remove_mapping(sh, args[1:])
                    if status:
                        message = list_mapping(team_id)
                        log.info(message)
                    else:
                        log.error(message)
            else:
                message = 'User %s is not an admin' % event['user_name']
                log.info(message)
    except Exception as e:
        log.exception(e)
        message = e.message
    return {
        "response_type": "in_channel",
        'text': message
    }

