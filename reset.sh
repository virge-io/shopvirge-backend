#!/bin/bash
echo "Dropping"
dropdb shop
echo "Creating"
createdb shop
echo "Populating"
psql -d shop < shop_prod.psql
