git pull
docker build . --tag ouranos:latest

docker run -d \
 --name ouranos \
 --network prod \
 -v $PWD/logs:/bulbe/ouranos \
 --restart unless-stopped \
 ouranos
