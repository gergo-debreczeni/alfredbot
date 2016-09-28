from __future__ import print_function

import logging
import os
import shlex
from subprocess import Popen, PIPE

import boto3
from pymemcache.client.hash import HashClient
import requests

log = logging.getLogger()
log.setLevel(logging.INFO)
MEMCACHED_ENDPOINT = 'alfredbot-users.atjtz9.cfg.euw1.cache.amazonaws.com'
MEMCACHED_PORT = 11211
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


def get_role(team_id, user_id):
    mc = MemCacheHelper()
    unique_id = '%s_%s' % (team_id, user_id)
    role = mc.get(unique_id)
    return role

def get_custom_env(role, team_name):
    client = boto3.client('sts')
    temp_creds = client.assume_role(RoleArn=role,
                                    RoleSessionName='alfredbot',
                                    ExternalId=team_name)
    key = temp_creds['Credentials']['AccessKeyId']
    secret = temp_creds['Credentials']['SecretAccessKey']
    token = temp_creds['Credentials']['SessionToken']
    invoke_env = os.environ.copy()
    invoke_env["AWS_ACCESS_KEY_ID"] = str(key)
    invoke_env["AWS_SECRET_ACCESS_KEY"] = str(secret)
    invoke_env["AWS_SECURITY_TOKEN"] = str(token)
    return invoke_env


def invoke(team_name, team_id, user_id, task):
    role = get_role(team_id, user_id)
    log.info('Role for user %s is %s' % (user_id, role))
    if not role:
        return False, 'No role found for user. \n' \
                      'Please configure roles using `/alfred-admin` and then sync using `/alfred-sync`.'
    custom_env = get_custom_env(role, team_name)

    if task:
        log.info('Submitted task was {0}'.format(task))
        polished_task = ['/usr/bin/python', 'aws.py'] + task
        try:
            p = Popen(polished_task, stdout=PIPE, stderr=PIPE, env=custom_env)
            stdout, stderr = p.communicate()
            message = '%s\n%s' % (stdout, stderr)
            log.info(message)
            return True, message
        except Exception as e:
            log.exception(e)
            return False, 'Something went wrong. Try again later.'


def bot_help():
    h = "Available commands `/alfred-invoke <aws command> `\n"
    h += "\nExample: `/alfred-invoke aws s3 ls `"
    h += "\n"
    h += "\n For more details see www.alfredbot.io/"
    return h


def handler(event, context):
    try:
        resp = None
        log.info(event)
        raw_text = event['text']
        team_name = event['team_domain']
        team_id = event['team_id']
        user_id = event['user_id']
        response_url = event['response_url']
        args = shlex.split(raw_text)
        if args[0] != 'aws':
            message = 'Unsuported command %s\n\n' % args[0]
            message += bot_help()
            log.error(message)
        else:
            # Somewhat workaround to slackbot timeout
            message = 'Wheels are in motion, sorry if this might take a bit.'
            requests.post(response_url, json={'text': message})
            status, message = invoke(team_name, team_id, user_id, args[1:])
            if not status:
                log.error(message)
            resp = {
                "response_type": "in_channel",
                'text': message
            }
            requests.post(response_url,
                          json=resp)
    except Exception as e:
        log.exception(e)
        message = e.message
    finally:
        if not resp:
            return {
                'text': message
            }
        else:
            return {
                'text': '\n'
            }
