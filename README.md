## Inspiration
Ever since the launch of slack, devOps are so 2015, this is the era of ChatOps!

What best way to enable slack users to leverage the sheer power of AWS than to bring the CLI to their favourite platform of communication?


## What it does

Alfredbot brings the full power of AWS CLI to slack. You can configure granular permissions by associating channels/groups/usergroups with different roles from your AWS account.


## How we built it

Alfredbot is split into 4 lambda functions, segregating responsibilities and limiting access to information as follows:


**Outsider** - gets triggered as the callback hook from installing Alfredbot to slack, parsing the code queryparam in API gateway. Using the code and client id/secret an oAuth token is generated, KMS encrypted and stored in dynamoDB.

**Eagle** - responsible for configuring the mapping between channels/groups/usergroups and AWS roles, only available for slack administrators. The information is saved in dynamoDB.

**Thaddeus** - after you're done configuring the mappings, invoke /alfred-sync start to synchronize the users belonging to previously configured channels/groups/usergroups and store them in memcached.

**Alfred** - entrypoint for your /alfred-invoke <aws command>, retrieves the role associated with the caller from memcached, assumes it and tries to execute the aws command.



## Challenges we ran into

Porting AWS CLI to lambda was a challenge, luckily under the hood it's a python package and with some clever engineering we managed to get it working from lambda.

Unfortunately certain aws commands even from terminal can take 2-3 seconds, with slacks default timeout of 3 seconds for a response for a slash command our main goal was performance, hence caching the invoker-role mapping and not determining it dynamically.

One thing we still suffer from are lambda 'cold' calls, but once Alfrebot will be popular that won't be a problem anymore!


## Accomplishments that we're proud of

Configuring API gateway and lambda to be used as slack redirect hook for installing the app was pretty ingenious if you ask me, everything is truly serverless.

Pretty proud of getting the CLI on lambda.


## What we learned

A lot, luckily there were some pretty awesome projects out there to make our lives easier lambkin/slacker/pynamodb/pymemcache, big shoutout to the maintainers!

Logs are your best friend when debugging API Gateway and lambda.

## What's next for Alfredbot

What we really want for alfredbot is full shell syntax support which is easy to do with Popen(shell=True) but that is a security hole in the application so we'll have to be more clever about it.

Multi-account support.

Aliases for frequently used commands.

Standalone installation for organizations that want to manage Alfredbot on their own. This is almost done.

Feel free to drop your suggestions on the github project!
