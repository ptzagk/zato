#!/bin/bash

declare -a repos
declare -a workdirs

repos=(
appzipper
configmanager
credentialsmanager
dbconnector
dbmanager
descriptionxml
devicemanager
licensemanager
organizationmanager
servicemanager
sqlalchemymodels
)

workdirs=(
appcloud
services
)

echo "Adding identity to the authentication client..."
eval `ssh-agent -s`
ssh-add .ssh/zato_deploy

echo "Creating directories to store Zato services and server objects..."
for dir in ${workdirs[@]}
do
    if [ ! -d $HOME/$dir ]
    then
        mkdir $HOME/$dir
        "Directory $dir created."
    fi
done
cd $HOME/appcloud

echo "Cloning repositories and copying services..."
for repo in ${repos[@]}
do
    if [ ! -d appcloud.$repo ]
    then
        git clone git@bitbucket.org:foxway/appcloud.$repo.git
        cd appcloud.$repo
        cp *.py $HOME/services
        cd ..
    fi
done
