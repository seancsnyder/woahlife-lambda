import boto3.dynamodb
import json
import os
import datetime
import time
import helper


def create_entry(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])

    json_body = json.loads(event['body'])

    print("Received journal entry for: " + json_body['date'])

    entry_key: int = int(json_body['date'])

    try:
        # Try to get an item by that entryDate
        table.get_item(Key={'date': entry_key})

        # Since we didn't throw, we need to append this message to the
        # existing item list.
        table.update_item(
            Key={'date': entry_key},
            UpdateExpression='SET entries = list_append(entries, :msg)',
            ExpressionAttributeValues={
                ':msg': [json_body['text']]
            }
        )

        print("Updated existing dynamodb item entry")

    except:
        # If we threw here, the item didn't exist, so create a new item
        table.put_item(
            Item={
                'date': entry_key,
                'entries': [json_body['text']]
            }
        )

        print("Writing new dynamodb item entry")

    return helper.return_success_json({'success': True})


def get_entry(event, context):
    entry_date = int(event['pathParameters']['date'])

    print("getting entry for: " + str(entry_date))

    algolia_index = helper.get_algolia_client()

    try:
        entry = algolia_index.get_object(
            str(entry_date),
            {
                'attributesToRetrieve': [
                    'date',
                    'entries',
                    'objectID',
                    'prettyDate'
                ]
            }
        )

        return helper.return_success_json(entry)
    except:
        return helper.return_404_json({})


def search_entries(event, context):
    """
    Function to search through the search index for a query
    """

    algolia_index = helper.get_algolia_client()

    query = event['queryStringParameters']['query']

    print("searching for: " + query)

    results = algolia_index.search(
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

    return helper.return_success_json(results)


def sync_entries_to_search_index(event, context):
    """
    Sync the dynamo db record to the search index.
    Triggered by a DynamoDb trigger on create/update/delete
    """

    algolia_index = helper.get_algolia_client()

    date_key = str(event['Records'][0]['dynamodb']['Keys']['date']['N'])

    print('syncing entries to search index for: ' + date_key)

    print(event)

    # unexpected, but could happen if aren't updating/creating a dynamodb item. Could be a deletion...
    if 'NewImage' not in event['Records'][0]['dynamodb']:
        if event['Records'][0]['eventName'] == "REMOVE":
            print("Removing item: " + date_key)

            algolia_index.delete_object(date_key)

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

    date = datetime.datetime(int(date_key[0:4]), int(date_key[4:6]), int(date_key[6:8]))

    pretty_date = date.strftime('%A %B %d %Y')
    timestamp = time.mktime(date.timetuple())

    body = {
        "objectID": date_key,
        "date": timestamp,
        "prettyDate": pretty_date,
        "entries": entries
    }

    print(body)

    if len(str(body)) > 10000:
        print("[ERROR] Unable to sync, records in Algolia will be too big")
    else:
        algolia_index.save_objects([body])

    return True
