import sys;

sys.path.insert(0, "./venv/lib/python3.8/site-packages")

from botocore.exceptions import ClientError
import boto3
import json
import os
import datetime
import time
from algoliasearch.search_client import SearchClient
from functools import reduce


def createEntry(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])

    jsonBody = json.loads(event['body'])

    print("Received journal entry for: " + jsonBody['date'])

    entryKey = int(jsonBody['date'])

    try:
        # Try to get an item by that entryDate
        table.get_item(Key={'date': entryKey})

        # Since we didn't throw, we need to append this message to the
        # existing item list.
        table.update_item(
            Key={'date': entryKey},
            UpdateExpression='SET entries = list_append(entries, :msg)',
            ExpressionAttributeValues={
                ':msg': [jsonBody['text']]
            }
        )

        print("Updated existing dynamodb item entry")

    except Exception as e:
        # If we threw here, the item didn't exist, so create a new item
        table.put_item(
            Item={
                'date': entryKey,
                'entries': [jsonBody['text']]
            }
        )

        print("Writing new dynamodb item entry")

    return {
        'statusCode': 200,
        'body': json.dumps({'success': True})
    }


def getEntry(event, context):
    entryDate = int(event['pathParameters']['date'])

    print("getting entry for: " + str(entryDate))

    algoliaClient = SearchClient.create(os.environ['ALGOLIA_APP_ID'], os.environ['ALGOLIA_APP_KEY'])
    algoliaIndex = algoliaClient.init_index(os.environ['ALGOLIA_INDEX_NAME'])

    try:
        entry = algoliaIndex.get_object(
            entryDate,
            {
                'attributesToRetrieve': [
                    'date',
                    'entries',
                    'objectID',
                    'prettyDate'
                ]
            }
        )

        return {
            'statusCode': 200,
            'body': json.dumps(entry)
        }
    except:
        return {
            'statusCode': 404,
            'body': '{}'
        }


def searchEntries(event, context):
    algoliaClient = SearchClient.create(os.environ['ALGOLIA_APP_ID'], os.environ['ALGOLIA_APP_KEY'])
    algoliaIndex = algoliaClient.init_index(os.environ['ALGOLIA_INDEX_NAME'])

    query = event['queryStringParameters']['query']

    print("searching for: " + query)

    results = algoliaIndex.search(
        query,
        {
            'attributesToRetrieve': [
                'date',
                'entries',
                'objectID',
                'prettyDate'
            ],
            'hitsPerPage': 100
        }
    )

    return {
        'statusCode': 200,
        'body': json.dumps(results)
    }


def syncEntriesToSearchIndex(event, context):
    algoliaClient = SearchClient.create(os.environ['ALGOLIA_APP_ID'], os.environ['ALGOLIA_APP_KEY'])
    algoliaIndex = algoliaClient.init_index(os.environ['ALGOLIA_INDEX_NAME'])

    dateKey = str(event['Records'][0]['dynamodb']['Keys']['date']['N'])

    print("syncing entries to search index for: " + dateKey)

    print(event)

    # unexpected, but could happen if aren't updating/creating a dynamodb item. Could be a deletion...
    if 'NewImage' not in event['Records'][0]['dynamodb']:
        if event['Records'][0]['eventName'] == "REMOVE":
            print("Removing item: " + dateKey)

            algoliaIndex.delete_object(dateKey)

            return True
        else:
            raise Exception(
                "NewImage data not in event payload. Unable to process event. Event Name: " + event['Records'][0][
                    'eventName'])

    if 'entries' not in event['Records'][0]['dynamodb']['NewImage']:
        print("No Entries found...")

        return True

    entries = []
    for entry in event['Records'][0]['dynamodb']['NewImage']['entries']['L']:
        entries.append(entry['S'])

    date = datetime.datetime(int(dateKey[0:4]), int(dateKey[4:6]), int(dateKey[6:8]))

    prettyDate = date.strftime('%A %B %d %Y')
    timestamp = time.mktime(date.timetuple())

    body = {
        "objectID": dateKey,
        "date": timestamp,
        "prettyDate": prettyDate,
        "entries": entries
    }

    print(body)

    if len(str(body)) > 10000:
        print("[ERROR] Unable to sync, records in Algolia will be too big")
    else:
        algoliaIndex.save_objects([body])

    return True
