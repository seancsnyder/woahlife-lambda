import base64
from botocore.exceptions import ClientError
import requests
import boto3
import boto3
import datetime
import dateutil.tz
import email
import json
import os
import re
from urllib.parse import unquote
from elasticsearch import Elasticsearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

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
            auth=("api", os.environ['MAILGUN_API_KEY']),
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

    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])
 
    mailgunPostBody = {}
    for item in event['body'].split("&"):
        keyValue = item.split("=");
        mailgunPostBody[keyValue[0]] = unquote(keyValue[1])

    response = requests.get(
        mailgunPostBody['message-url'],
        auth=("api", os.environ['MAILGUN_API_KEY']))

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
    except Exception as e:
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
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])
    
    foundEntries = 0

    mailgunPostBody = {}
    for item in event['body'].split("&"):
        keyValue = item.split("=");
        mailgunPostBody[keyValue[0]] = unquote(keyValue[1])

    response = requests.get(
        mailgunPostBody['message-url'],
        auth=("api", os.environ['MAILGUN_API_KEY']))

    message = response.json()

    requestSubject = message['subject']

    #Assume we'll use today's year, unless the subject line had the year
    pacific = dateutil.tz.gettz('US/Pacific')
    pacificDate = datetime.datetime.now(tz=pacific)
    currentYear = int(pacificDate.strftime("%Y"))
    currentMonth = int(pacificDate.strftime("%m"))
    currentDay = int(pacificDate.strftime("%d"))

    #Default to current year of entries
    dateCursor = datetime.datetime(currentYear, 1, 1)
    endDate = datetime.datetime(currentYear, 12, 31)

    #hardcode some subjects that can shortcut to time periods
    if requestSubject.lower() == "week":
        dateCursor = datetime.datetime(currentYear, currentMonth, currentDay)
        
        lastSevenDaysStep = datetime.timedelta(days=7)
        dateCursor = dateCursor - lastSevenDaysStep
        
        endDate = datetime.datetime(currentYear, currentMonth, currentDay)
    
        print("Attempting to browse journal entries for the last 7 days")
            
        responseSubject = "Woahlife Entries - Last 7 Days"
    elif requestSubject == "month":
        dateCursor = datetime.datetime(currentYear, currentMonth, currentDay)
        
        lastThirtyDaysStep = datetime.timedelta(days=31)
        dateCursor = dateCursor - lastThirtyDaysStep
        
        endDate = datetime.datetime(currentYear, currentMonth, currentDay)
    
        print("Attempting to browse journal entries for the last 31 days")
            
        responseSubject = "Woahlife Entries - Last 31 Days"
    elif len(requestSubject) >= 4:
        #Parse the last 4 digits off the subject. It'll be the year
        subjectDate = requestSubject[len(requestSubject)-4:len(requestSubject)]

        if subjectDate.isdigit():
            browseYear = int(subjectDate)

            dateCursor = datetime.datetime(currentYear, currentMonth, currentDay)
    
        print("Attempting to browse journal entries for year: " + str(browseYear))
            
        responseSubject = "Woahlife Entries " + str(browseYear)


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
            auth=("api", os.environ['MAILGUN_API_KEY']),
            data={
                "from": "Woahlife <post@woahlife.com>",
                "to": [os.environ['TO_EMAIL_ADDRESS']],
                "subject": responseSubject,
                "text": responseBody
            }
        )
    except Exception as e:
        print(e.response['Error']['Message'])

        raise e
    else:
        return {
            'statusCode': 200,
            'body': "OK"
        }

def cleanupEntries(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])
    
    pacific = dateutil.tz.gettz('US/Pacific')
    pacificDate = datetime.datetime.now(tz=pacific)
    currentYear = int(pacificDate.strftime("%Y"))
    currentMonth = int(pacificDate.strftime("%m"))
    currentDay = int(pacificDate.strftime("%d"))

    dateCursor = datetime.datetime(2005, 1, 1)
    endDate = datetime.datetime(currentYear, currentMonth, currentDay)

    dateCursorStep = datetime.timedelta(days=1)
        
    while dateCursor <= endDate:
        dateKey = int(dateCursor.strftime('%Y%m%d'))
        
        # Try to get an item by that dateKey
        response = table.get_item(Key={'date': dateKey})
        
        if 'Item' in response.keys():
            entries = response['Item']['entries']

            for key, entry in enumerate(response['Item']['entries']):
                cleanedEntry = entry

                cleanedEntry = cleanedEntry.replace("=E2=80=99", "'")
                cleanedEntry = cleanedEntry.replace("= ", "")

                entries[key] = cleanedEntry

            table.update_item(
                Key={'date': dateKey},
                UpdateExpression='SET entries = :entries',
                ExpressionAttributeValues={
                    ':entries': entries
                }
            )

            print("Cleaned up: " + str(dateKey))

        dateCursor += dateCursorStep

    return True

def syncElasticSearch(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])

    credentials = boto3.Session().get_credentials()

    es = Elasticsearch(
        hosts = [{'host': os.environ['ELASTICSEARCH_HOST'], 'port': 443}],
        http_auth = AWS4Auth(credentials.access_key, credentials.secret_key, 'us-west-2', 'es', session_token=credentials.token),
        use_ssl = True,
        verify_certs = True,
        connection_class = RequestsHttpConnection
    )

    # ignore 400 cause by IndexAlreadyExistsException when creating an index
    es.indices.create(index=os.environ['ELASTICSEARCH_JOURNALENTRY_INDEX'], ignore=400)

    entries = []
    for entry in event['Records'][0]['dynamodb']['NewImage']['entries']['L']:
        entries.append(entry['S'])

    dateKey = event['Records'][0]['dynamodb']['Keys']['date']['N']
    
    #build the object we want to store in elasticsearch
    body = json.JSONEncoder().encode({"entry": {"entries": entries}})
    #TODO add other things we wanna search on...
    #add all the things we'd normally browse for?

    es.index(index=os.environ['ELASTICSEARCH_JOURNALENTRY_INDEX'], body=body, id=dateKey)

    return True

def rebuildElasticSearch(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])

    credentials = boto3.Session().get_credentials()

    es = Elasticsearch(
        hosts = [{'host': os.environ['ELASTICSEARCH_HOST'], 'port': 443}],
        http_auth = AWS4Auth(credentials.access_key, credentials.secret_key, 'us-west-2', 'es', session_token=credentials.token),
        use_ssl = True,
        verify_certs = True,
        connection_class = RequestsHttpConnection
    )

    # ignore 400 cause by IndexAlreadyExistsException when creating an index
    es.indices.create(index=os.environ['ELASTICSEARCH_JOURNALENTRY_INDEX'], ignore=400)
    
    pacific = dateutil.tz.gettz('US/Pacific')
    pacificDate = datetime.datetime.now(tz=pacific)
    currentYear = int(pacificDate.strftime("%Y"))
    currentMonth = int(pacificDate.strftime("%m"))
    currentDay = int(pacificDate.strftime("%d"))

    dateCursor = datetime.datetime(2005, 1, 1)
    endDate = datetime.datetime(currentYear, currentMonth, currentDay)

    dateCursorStep = datetime.timedelta(days=1)
        
    while dateCursor <= endDate:
        dateKey = int(dateCursor.strftime('%Y%m%d'))
        
        # Try to get an item by that dateKey
        response = table.get_item(Key={'date': dateKey})
        
        if 'Item' in response.keys():
           
            body = json.JSONEncoder().encode({"entry": {"entries": response['Item']['entries']}})
            #TODO add other things we wanna search on...

            es.index(index=os.environ['ELASTICSEARCH_JOURNALENTRY_INDEX'], body=body, id=dateKey)

            print("rebuilt index for entry: " + str(dateKey))

        dateCursor += dateCursorStep

    return True

def searchEntries(event, context):
    credentials = boto3.Session().get_credentials()

    es = Elasticsearch(
        hosts = [{'host': os.environ['ELASTICSEARCH_HOST'], 'port': 443}],
        http_auth = AWS4Auth(credentials.access_key, credentials.secret_key, 'us-west-2', 'es', session_token=credentials.token),
        use_ssl = True,
        verify_certs = True,
        connection_class = RequestsHttpConnection
    )

    # ignore 400 cause by IndexAlreadyExistsException when creating an index
    es.indices.create(index=os.environ['ELASTICSEARCH_JOURNALENTRY_INDEX'], ignore=400)
    
    results = es.search(index=os.environ['ELASTICSEARCH_JOURNALENTRY_INDEX'], body=json.JSONEncoder().encode({"query" : {"match" : {"entry.entries" : "bunny"}}}))
        
    for result in results['hits']:
        print(result)

    return True    