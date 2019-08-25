import base64
from botocore.exceptions import ClientError
from botocore.vendored import requests
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
import boto3
import datetime
import dateutil.tz
import email
import json
import os
import re
from urllib.parse import unquote


def get_mailgunapi_secret():
    secret_name = os.environ['MAILGUN_API_SSM_KEY']
    region_name = os.environ['MAILGUN_API_SSM_REGION']

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    # In this sample we only handle the specific exceptions for the 'GetSecretValue' API.
    # See https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
    # We rethrow the exception by default.

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        raise e
    else:
        # Decrypts secret using the associated KMS CMK.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            decodedSecret = get_secret_value_response['SecretString']
        else:
            decodedSecret = base64.b64decode(get_secret_value_response['SecretBinary'])

    # Secret is stored as a json key/value decoded string
    decodedSecretJson = json.loads(decodedSecret)

    if 'MAILGUN_API_KEY' not in decodedSecretJson:
        raise Exception("Unable to find the key in the decoded json encoded object")

    return decodedSecretJson['MAILGUN_API_KEY']


def requestEntry(event, context):
    emailAddress = os.environ['TO_EMAIL_ADDRESS']
    
    pacific = dateutil.tz.gettz('US/Pacific')
    pacificDate = datetime.datetime.now(tz=pacific)

    prompt = "Forecast" if int(pacificDate.strftime("%H")) < 12 else "Reflect"

    subjectDateKey = pacificDate.strftime("%Y%m%d")
    subject = pacificDate.strftime("%a %b %d, %Y")
    subject += " - " + prompt
    subject += " - " + pacificDate.strftime("%Y%m%d")
    
    body = "Hey, how's it going?"

    try:
        requests.post(
            "https://api.mailgun.net/v3/woahlife.com/messages",
            auth=("api", get_mailgunapi_secret()),
            data={
                "from": "Woahlife <post@woahlife.com>",
                "to": ["sean@snyderitis.com"],
                "subject": subject,
                "text": body
            }
        )
    except Exception as e:
        print(str(e))

        raise e
    else:
        print("Sent: journal entry (" + subject + ") to " + emailAddress)
        return {
            'statusCode': 200,
            'body': "OK"
        }


def receiveEntry(event, context):
    dynamodb = boto3.resource('dynamodb')

    table = dynamodb.Table('woahlife_entries')
 
    mailgunPostBody = {}
    for item in event['body'].split("&"):
        keyValue = item.split("=");
        mailgunPostBody[keyValue[0]] = unquote(keyValue[1])

    response = requests.get(
        mailgunPostBody['message-url'],
        auth=("api", get_mailgunapi_secret()))

    message = response.json()

    body = message['stripped-text']
    subject = message['subject']

    #Assume we'll use today's date, unless the subject line had the dateKey
    pacific = dateutil.tz.gettz('US/Pacific')
    pacificDate = datetime.datetime.now(tz=pacific)
    todayDate = pacificDate.strftime("%Y%m%d") 
    dateKey = int(todayDate)
    
    #Parse the last 8 digits off the subject.
    if len(subject) >= 8:
        print("date found on subject line")
        
        subjectDate = subject[len(subject)-8:len(subject)]

        if subjectDate.isdigit():
            dateKey = int(subjectDate)

    print("Received journal entry for: " + str(dateKey))
    
    try:
        #Try to get an item by that dateKey
        response = table.get_item(Key={'date': dateKey})
        
        #Since we didn't throw, we need to append this message to the
        #existing item list.
        table.update_item(
            Key={'date': dateKey},
            UpdateExpression='SET entries = list_append(entries, :msg)',
            ExpressionAttributeValues={
                ':msg': [body]
            }
        )
        
        print("Updated existing dynamodb item entry")
    except:
        #If we threw here, the item didn't exist, so create a new item
        table.put_item(
           Item={
                'date': dateKey,
                'entries': [body]
            }
        )
        
        print("Writing new dynamodb item entry")
    return {
        'statusCode': 200,
        'body': "OK"
    }



def browseEntries(event, context):   
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('woahlife_entries')
    
    foundEntries = 0

    mailgunPostBody = {}
    for item in event['body'].split("&"):
        keyValue = item.split("=");
        mailgunPostBody[keyValue[0]] = unquote(keyValue[1])

    response = requests.get(
        mailgunPostBody['message-url'],
        auth=("api", get_mailgunapi_secret()))

    message = response.json()

    requestSubject = message['subject']

    #Assume we'll use today's year, unless the subject line had the year
    pacific = dateutil.tz.gettz('US/Pacific')
    pacificDate = datetime.datetime.now(tz=pacific)
    browseYear = int(pacificDate.strftime("%Y"))

    #Parse the last 4 digits off the subject. It'll be the year
    if len(requestSubject) >= 4:
        subjectDate = requestSubject[len(requestSubject)-4:len(requestSubject)]

        if subjectDate.isdigit():
            browseYear = int(subjectDate)
            
    print("Attempting to browse journal entries for year: " + str(browseYear))
            
    responseSubject = "Woahlife Entries " + str(browseYear)

    dateCursor = datetime.datetime(browseYear, 1, 1)
    endDate = datetime.datetime(browseYear, 12, 31)
    dateCursorStep = datetime.timedelta(days=1)
    
    responseBody = "Here are your entries:\n\n";
    
    while dateCursor <= endDate:
        currentDate = dateCursor.strftime('%Y-%m-%d')
        dateKey = int(dateCursor.strftime('%Y%m%d'))
        
        # Try to get an item by that dateKey
        response = table.get_item(Key={'date': dateKey})
        
        if 'Item' in response.keys():
            foundEntries +=1
            
            entryDate = str(response['Item']['date'])
            
            responseBody += entryDate[0:4] + "-" + entryDate[4:6] + "-" + entryDate[6:8] + "\n"
            
            for entry in response['Item']['entries']:
                responseBody += entry + "\n\n"

        dateCursor += dateCursorStep
        
    print("Found: " + str(foundEntries) + " journal entries")
    
    try:
        requests.post(
            "https://api.mailgun.net/v3/woahlife.com/messages",
            auth=("api", get_mailgunapi_secret()),
            data={
                "from": "Woahlife <post@woahlife.com>",
                "to": [os.environ['TO_EMAIL_ADDRESS']],
                "subject": responseSubject,
                "text": responseBody
            }
        )
    except ClientError as e:
        print(e.response['Error']['Message'])

        raise e
    else:
        return {
            'statusCode': 200,
            'body': "OK"
        }