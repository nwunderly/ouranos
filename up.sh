git pull
docker build . --tag ouranos:latest

docker run -d \
 --name ouranos \
 --network prod \
 -v $PWD/logs:/ouranos/logs \
 -v $PWD/data:/ouranos/data \
 --restart unless-stopped \
 ouranos
