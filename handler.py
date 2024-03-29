import base64
import datetime
import json
import os
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


def find_missing_month_entries(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

    date_in_month = event['pathParameters']['date']

    today = datetime.date.today()

    date_obj = datetime.date(int(date_in_month[0:4]), int(date_in_month[4:6]), int(date_in_month[6:8]))

    # we always have a first of the month as our starting point
    start_of_month = datetime.date(date_obj.year, date_obj.month, 1)

    # find some date next month
    sometime_next_month = start_of_month + datetime.timedelta(days=40)

    # figure out when next month starts and then subtract one day to get the end of the current month
    start_of_next_month = datetime.date(sometime_next_month.year, sometime_next_month.month, 1)
    end_of_month = start_of_next_month - datetime.timedelta(days=1)

    current_date = start_of_month
    date_keys_missing = {}

    # don't include today or any dates in the future.
    # give me a chance to fill out today's entry before complaining that i missed a day
    while current_date <= end_of_month and current_date < today:
        date_key = str(current_date).replace("-", "")
        date_keys_missing[date_key] = True

        current_date = current_date + datetime.timedelta(days=1)

    # Check dynamodb to see what dates we've already recorded
    response = dynamodb.batch_get_item(RequestItems={
        table.name: {
            'Keys': [{'date': int(str(day).replace("-", ""))} for day in date_keys_missing],
            'AttributesToGet': [
                'date',
            ]
        }
    })

    if response["ResponseMetadata"]['HTTPStatusCode'] != 200:
        print("non 200 response:" + str(response["ResponseMetadata"]))
        return {
            'statusCode': 500,
            'body': json.dumps({'success': False})
        }

    for item in response["Responses"][table.name]:
        date_key = str(int(item["date"]))

        if date_key in date_keys_missing:
            del date_keys_missing[date_key]

    return {
        'statusCode': 200,
        'body': json.dumps({'success': True, 'missing_dates': list(date_keys_missing.keys())})
    }


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

        encrypted_some_entries = False

        for item in response["Items"]:
            for key, value in enumerate(item["entries"]):
                if isinstance(value, str):
                    encryption_response = kms.encrypt(
                        KeyId=os.environ["KMS_KEY_ARN"],
                        Plaintext=value
                    )
                    item["entries"][key] = encryption_response["CiphertextBlob"]
                    encrypted_some_entries = True

            if encrypted_some_entries:
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
