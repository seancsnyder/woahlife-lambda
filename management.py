import sys;

sys.path.insert(0, "./venv/lib/python3.8/site-packages")

from botocore.exceptions import ClientError
import requests
import boto3
import time
import datetime
import dateutil.tz
import json
import os
from urllib.parse import unquote
from algoliasearch.search_client import SearchClient

def rebuildSearchIndex(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])

    credentials = boto3.Session().get_credentials()

    algoliaClient = SearchClient.create(os.environ['ALGOLIA_APP_ID'], os.environ['ALGOLIA_APP_KEY'])
    algoliaIndex = algoliaClient.init_index(os.environ['ALGOLIA_INDEX_NAME'])

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
        prettyDate = dateCursor.strftime('%A %B %d %Y')
        timestamp = time.mktime(dateCursor.timetuple())

        # Try to get an item by that dateKey
        response = table.get_item(Key={'date': dateKey})

        if 'Item' in response.keys():

            # Add other things we wanna search on...
            body = {
                "objectID": str(dateKey),
                "date": timestamp,
                "prettyDate": prettyDate,
                "entries": response['Item']['entries']
            }

            res = algoliaIndex.save_objects([body])

            print("rebuilt index for entry: " + str(dateKey))

        dateCursor += dateCursorStep

    return True

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