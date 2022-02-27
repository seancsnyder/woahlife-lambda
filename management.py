import boto3
import time
import datetime
import dateutil.tz
import os
import algolia_helper


def rebuild_search_index(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])

    algolia_index = helper.get_algolia_client()

    pacific = dateutil.tz.gettz('US/Pacific')
    pacific_date = datetime.datetime.now(tz=pacific)
    current_year = int(pacific_date.strftime("%Y"))
    current_month = int(pacific_date.strftime("%m"))
    current_day = int(pacific_date.strftime("%d"))

    date_cursor = datetime.datetime(2005, 1, 1)
    end_date = datetime.datetime(current_year, current_month, current_day)

    date_cursor_step = datetime.timedelta(days=1)

    while date_cursor <= end_date:
        date_key = int(date_cursor.strftime('%Y%m%d'))
        pretty_date = date_cursor.strftime('%A %B %d %Y')
        timestamp = time.mktime(date_cursor.timetuple())

        # Try to get an item by that date_key
        response = table.get_item(Key={'date': date_key})

        if 'Item' in response.keys():
            # Add other things we wanna search on...
            body = {
                "objectID": str(date_key),
                "date": timestamp,
                "pretty_date": pretty_date,
                "entries": response['Item']['entries']
            }

            algolia_index.save_objects([body])

            print("rebuilt index for entry: " + str(date_key))

        date_cursor += date_cursor_step

    return True


def cleanup_entries(event, context):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(os.environ['DYANMODB_TABLE'])

    pacific = dateutil.tz.gettz('US/Pacific')
    pacific_date = datetime.datetime.now(tz=pacific)
    current_year = int(pacific_date.strftime("%Y"))
    current_month = int(pacific_date.strftime("%m"))
    current_day = int(pacific_date.strftime("%d"))

    date_cursor = datetime.datetime(2005, 1, 1)
    end_date = datetime.datetime(current_year, current_month, current_day)

    date_cursor_step = datetime.timedelta(days=1)

    while date_cursor <= end_date:
        date_key = int(date_cursor.strftime('%Y%m%d'))

        # Try to get an item by that date_key
        response = table.get_item(Key={'date': date_key})

        if 'Item' in response.keys():
            entries = response['Item']['entries']

            for key, entry in enumerate(response['Item']['entries']):
                cleaned_entry = entry

                cleaned_entry = cleaned_entry.replace("=E2=80=99", "'")
                cleaned_entry = cleaned_entry.replace("= ", "")

                entries[key] = cleaned_entry

            table.update_item(
                Key={'date': date_key},
                UpdateExpression='SET entries = :entries',
                ExpressionAttributeValues={
                    ':entries': entries
                }
            )

            print("Cleaned up: " + str(date_key))

        date_cursor += date_cursor_step

    return True
