#!/bin/bash
sudo sed -i "s/^#*listen_addresses.*/listen_addresses = '*'/" /etc/postgresql/16/main/postgresql.conf
sudo sed -i "s/^bind .*/bind 0.0.0.0/" /etc/redis/redis.conf
sudo service postgresql restart
sudo service redis-server restart
echo "--- WSL listen after fix ---"
ss -tlnp 2>/dev/null | grep -E ":5432|:6379"
