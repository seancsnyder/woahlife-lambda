import json
import os

from algoliasearch.search_client import SearchClient

def get_algolia_client() -> SearchClient:
    algolia_client = SearchClient.create(os.environ['ALGOLIA_APP_ID'], os.environ['ALGOLIA_APP_KEY'])
    algolia_index = algolia_client.init_index(os.environ['ALGOLIA_INDEX_NAME'])

    return algolia_index

def return_success_json(data: object) -> object:
    return {
        'statusCode': 200,
        'body': json.dumps(data)
    }

def return_404_json(data: object) -> object:
    return {
        'statusCode': 404,
        'body': json.dumps(data)
    }