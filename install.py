import sys
import time
import botocore
import boto3
from subprocess import Popen, PIPE


def get_stack_output(cf_client, stack_name):
    transition_state = ['CREATE_IN_PROGRESS', 'ROLLBACK_IN_PROGRESS', 'DELETE_IN_PROGRESS', 'UPDATE_IN_PROGRESS',
                        'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS', 'UPDATE_ROLLBACK_IN_PROGRESS',
                        'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS']
    completed_state = ['CREATE_COMPLETE', 'DELETE_COMPLETE', 'UPDATE_COMPLETE']
    stack_state = 'CREATE_IN_PROGRESS'
    response = {}
    while True:
        response = cf_client.describe_stacks(StackName=stack_name)
        stack_state = str(response['Stacks'][0]['StackStatus'])

        if stack_state in transition_state:
            print('Stack: ' + stack_name + ' is in transition: ' + stack_state)
            print('Waiting 30 seconds...')
            time.sleep(30)
            print(stack_state)
        else:
            break

    if stack_state in completed_state:
        outputs = {}
        output_list = response['Stacks'][0].get('Outputs', [])
        for output in output_list:
            outputs[output['OutputKey']] = output['OutputValue']
        return outputs
    else:
        return None


def cf_stack_exists(cf_client, stack_name):
    try:
        cf_client.describe_stacks(StackName=stack_name)
    except botocore.exceptions.ClientError as e:
        if "ValidationError" in str(e):
            return False
        else:
            raise e
    else:
        return True


def create_or_update_stack(cf_client, update, stack_name, template, parameters):
    if update:
        try:
            cf_client.update_stack(StackName=stack_name, TemplateBody=template, Parameters=parameters,
                                   Capabilities=['CAPABILITY_IAM'])
        except botocore.exceptions.ClientError as e:
            if 'No updates are to be performed' in e.message:
                print 'No updates required for stack: ' + stack_name
            else:
                raise e

    else:
        cf_client.create_stack(StackName=stack_name, TemplateBody=template, Parameters=parameters,
                               OnFailure='ROLLBACK', TimeoutInMinutes=60, Capabilities=['CAPABILITY_IAM'])


def read_stack_file(path):
    with open(path, 'r') as template_file:
        return template_file.read()


def install_lambda(role_name, lambda_function_name):
    if not role_name:
        print 'Lambda role already installed, skipping'
        return

    try:
        p = Popen("cd %s ; lambkin build ; lambkin publish --description 'Serverless demo bot' --role %s"
                  % (lambda_function_name, role_name),
                  stdout=PIPE, stderr=PIPE, shell=True)
        stdout, stderr = p.communicate()
        return lambda_function_name

    except Exception as e:
        print stdout
        print stderr
        print "Exception, while installing lambda: " + e.message


def install_stack(cf_client, stack_name, template_path, parameters=[]):
    update = cf_stack_exists(cf_client, stack_name)
    template = read_stack_file(template_path)
    create_or_update_stack(cf_client, update, stack_name, template, parameters)

    outputs = get_stack_output(cf_client, stack_name)

    if outputs:
        return outputs
    else:
        print("Stack {} has either FAILED or has no outputs, so I am unable to proceed.".format(stack_name))


def main():
    if len(sys.argv) < 4:
        print 'Please read README.md for usage instruction.'
        sys.exit(2)

    profile = str(sys.argv[1])
    region = str(sys.argv[2])
    slack_team_id = str(sys.argv[3])

    session = boto3.Session(region_name=region, profile_name=profile)
    cf_client = session.client('cloudformation')

    lambda_role_outputs = install_stack(cf_client, 'alfredrole', 'alfred/lambda_role.json')
    assumed_role = lambda_role_outputs.get('AlfredAssumedRole', None)
    assumed_role_arn = lambda_role_outputs.get('AlfredAssumedRoleArn', None)
    lambda_function_name = install_lambda(assumed_role, 'bot')

    install_stack(cf_client, 'alfred-apigateway', 'deploy/deploy_stack.json', parameters=[
        {'ParameterKey': 'LambdaFunctionName', 'ParameterValue': lambda_function_name, 'UsePreviousValue': False}])

    install_stack(cf_client, 'alfred-full', 'deploy/deploy_assumed_roles.json', parameters=[
        {'ParameterKey': 'AlfredAssumedRoleArn', 'ParameterValue': assumed_role_arn, 'UsePreviousValue': False},
        {'ParameterKey': 'CreateAdminRole', 'ParameterValue': "yes", 'UsePreviousValue': False},
        {'ParameterKey': 'CreateOpsRole', 'ParameterValue': "yes", 'UsePreviousValue': False},
        {'ParameterKey': 'CreateReadOnlyRole', 'ParameterValue': "yes", 'UsePreviousValue': False},
        {'ParameterKey': 'SlackTeamDomain', 'ParameterValue': slack_team_id, 'UsePreviousValue': False}])

    eagle_role_outputs = install_stack(cf_client, 'eagle', 'eagle/lambda_role.json')
    install_lambda(eagle_role_outputs.get('EagleAssumedRole', None), 'eagle')

    outsider_role_outputs = install_stack(cf_client, 'outsider', 'outsider/lambda_role.json')
    install_lambda(outsider_role_outputs.get('OutsiderAssumedRole', None), 'outsider')

    thaddeus_role_outputs = install_stack(cf_client, 'thaddeus', 'thaddeus/lambda_role.json')
    install_lambda(thaddeus_role_outputs.get('ThaddeusAssumedRole', None), 'thaddeus')


if __name__ == '__main__':
    main()
