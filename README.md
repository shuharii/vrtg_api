# Create
curl -X POST "https://vertigo-clan-api-o4pxlvjv7q-ez.a.run.app/clans" -H "content-type: application/json" -d '{"name":"Alpha","region":"EU"}'

# List
curl "https://vertigo-clan-api-o4pxlvjv7q-ez.a.run.app/clans"

curl -X GET "https://vertigo-clan-api-o4pxlvjv7q-ez.a.run.app/clans?region=EU"

# Delete
curl -X DELETE "https://vertigo-clan-api-o4pxlvjv7q-ez.a.run.app/clans/ff2c46c8-0e29-437e-b29d-3bf7df6c083b"

curl -i "https://vertigo-clan-api-o4pxlvjv7q-ez.a.run.app/clans/b9e79c5a-1317-4aa6-a7d7-119d1f722fd7"

curl -s "https://vertigo-clan-api-o4pxlvjv7q-ez.a.run.app/clans?region=TR&sort_by=name&order=asc"
