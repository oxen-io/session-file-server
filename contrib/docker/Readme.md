# Docker for Session File Server development

The file DockerFile.dev is specifically made for development if you are not running linux.
It lets you create a docker running linux and the session-file-server in it even if you are running Macos or Windows.
It creates a docker container with the content of this git repository mounted.
Basically, whatever you edit in this repository will be represented on the docker container. So when you run the container, it will run your code.

> **WARNING**: Not for production use. This docker image is strictly for development use and not supported for production use.

## Build the container image

You need to have docker installed on your computer. Follow the docker documentation for your system first.
Once you can run the hello world from github you should be fine

```
docker run hello-world # this command should print "Hello from Docker!"
```

Then, build the container image for session-file-server-dev as

```
git clone git@github.com:oxen-io/session-file-server.git
cd session-file-server
docker build . -f contrib/docker/Dockerfile.dev -t session-file-server
```

> **WARNING**: Not for production use. This docker image is strictly for development use and not supported for production use.
Next, you can run and attach to the container with

```
docker run -d -p 8000:80 --name session-file-server-container session-file-server
```
