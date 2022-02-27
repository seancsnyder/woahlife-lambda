import base64
import json
import os
import datetime
import time

import boto3.dynamodb

import algolia_helper


def create_entry(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

    json_body = json.loads(event['body'])

    kms = boto3.client("kms")
    encryption_response = kms.encrypt(
        KeyId=os.environ["KMS_KEY_ARN"],
        Plaintext=bytes(json_body['text'], encoding='utf8'),
    )

    entry_key: int = int(json_body['date'])
    entry_text: bytes = encryption_response["CiphertextBlob"]

    print(entry_key)
    print(entry_text)

    try:
        # Try to get an item by that entryDate
        table.get_item(Key={'date': entry_key})

        # Since we didn't throw, we need to append this message to the
        # existing item list.
        table.update_item(
            Key={'date': entry_key},
            UpdateExpression='SET entries = list_append(entries, :msg)',
            ExpressionAttributeValues={
                ':msg': [entry_text]
            }
        )

        print("Updated existing dynamodb item entry")

    except:
        # If we threw here, the item didn't exist, so create a new item
        table.put_item(
            Item={
                'date': entry_key,
                'entries': [entry_text]
            }
        )

        print("Writing new dynamodb item entry")

    return algolia_helper.return_success_json({'success': True})


def get_entry(event, context):
    entry_date = int(event['pathParameters']['date'])

    print("getting entry for: " + str(entry_date))

    algolia_index = algolia_helper.get_algolia_client()

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

        return algolia_helper.return_success_json(entry)
    except:
        return algolia_helper.return_404_json({})


def search_entries(event, context):
    """
    Function to search through the search index for a query
    """

    algolia_index = algolia_helper.get_algolia_client()

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

    return algolia_helper.return_success_json(results)


def sync_entries_to_search_index(event, context):
    """
    Sync the dynamo db record to the search index.
    Triggered by a DynamoDb trigger on create/update/delete
    """
    print(event)
    algolia_index = algolia_helper.get_algolia_client()

    for record in event["Records"]:
        date_key = str(record['dynamodb']['Keys']['date']['N'])

        print('syncing entries to search index for: ' + date_key)
        print(record)

        # unexpected, but could happen if aren't updating/creating a dynamodb item. Could be a deletion...
        if 'NewImage' not in record['dynamodb']:
            if record['eventName'] == "REMOVE":
                print("Removing item: " + date_key)

                algolia_index.delete_object(date_key)
            else:
                raise Exception("NewImage data not in event payload. Unable to process event. Event Name: " + record['eventName'])

        elif "NewImage" in record['dynamodb'] and 'entries' in record['dynamodb']['NewImage']:
            kms = boto3.client("kms")

            entries = []
            for entry in record['dynamodb']['NewImage']['entries']['L']:
                if "S" in entry:
                    entries.append(entry["S"])
                elif "B" in entry:
                    kms_response = kms.decrypt(
                        KeyId=os.environ["KMS_KEY_ARN"],
                        CiphertextBlob=base64.b64decode(entry['B'])
                    )
                    entries.append(kms_response["Plaintext"].decode('utf8'))

            date = datetime.datetime(int(date_key[0:4]), int(date_key[4:6]), int(date_key[6:8]))

            pretty_date = date.strftime('%A %B %d %Y')
            timestamp = time.mktime(date.timetuple())

            body = {
                "objectID": date_key,
                "date": timestamp,
                "prettyDate": pretty_date,
                "entries": entries
            }

            if len(str(body)) > 10000:
                raise Exception("[ERROR] Unable to sync, records in Algolia will be too big")
            else:
                algolia_index.save_objects([body])

        else:
            raise Exception("Unknown event...")

    return True


def encrypt_unencrypted_entries(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

    kms = boto3.client("kms")

    scan_kwargs = {}

    done = False
    start_key = None

    while not done:
        if start_key:
            scan_kwargs['ExclusiveStartKey'] = start_key

        response = table.scan(**scan_kwargs)

        encryptedSomeEntries = False

        for item in response["Items"]:
            print(item)

            for key, value in enumerate(item["entries"]):
                if isinstance(value, str):
                    encryption_response = kms.encrypt(
                        KeyId=os.environ["KMS_KEY_ARN"],
                        Plaintext=value
                    )
                    item["entries"][key] = encryption_response["CiphertextBlob"]
                    encryptedSomeEntries = True

            if encryptedSomeEntries:
                print(item)

                # update the item
                response = table.update_item(
                    Key={
                        'date': int(item["date"])
                    },
                    UpdateExpression="set entries=:a",
                    ExpressionAttributeValues={
                        ':a': item["entries"]
                    },
                    ReturnValues="UPDATED_NEW"
                )

                if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
                    print(response)

        start_key = response.get('LastEvaluatedKey', None)
        done = start_key is None
