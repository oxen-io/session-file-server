# Session File Server

This is the Session file server that hosts encrypted avatars and attachments for the Session
network.  It is effectively a "dumb" store of data as it simply stores, retrieves, and expires but
cannot read the encrypted blobs.

It has one additional feature used by Session which is acting as a cache and server of the current
version of Session (as posted on GitHub) to allow Session clients to check the version without
leaking metadata (by making an onion request through the Oxen service node network).

## Requires

### Python3

A reasonably recent version of Python 3 (3.8 or newer are tested, earlier may or may not work), with
the following modules installed.  (Most of these are available as `apt install python3-NAME` on
Debian/Ubuntu).
- flask
- coloredlogs
- psycopg 3.x (*not* the older psycopg2 currently found in most linux distros)
- psycopg_pool
- requests

Additionally you need to build the Oxen Project's pyoxenmq and pylibonionreq.  This repository links
to them as submodules; `make` will build them locally for simple setups (proper deb packaging of
those libs is still a TODO).

### WSGI request handler

The file server uses WSGI for incoming HTTP requests.  See below for one possible way to set this
up.

### PostgreSQL

Everything is stored in PostgreSQL; no local file storage is used at all.

## Getting started

0. Create a user, clone the code as a user, run the code as a user, NOT as root.

1. Install the required Python packages:

    ```bash
       sudo apt install python3 python3-flask python3-coloredlogs python3-requests python3-pip

       pip3 install psycopg psycopg_pool  # Or as above, once these enter Debian/Ubuntu
    ```

2. Build the required oxen Python modules:

       make

3. Set up a postgresql database for the files to live in.  Note that this can be *large* because
   file content is stored in the database, so ensure it is on a filesystem with lots of available
   storage.

   A quick setup, if you've never used it before, is:
   
   ```bash
   sudo apt install postgresql-server postgresql-client  # Install server and client
   sudo su - postgres  # Change to postgres system user
   createuser YOURUSER  # Replace with your username, *NOT* root
   createdb -O YOURUSER sessionfiles  # Creates an empty database for session files, owned by you
   exit  # Exit the postgres shell, return to your user

   # Test that postgresql lets us connect to the database:
   echo "select 'hello'" | psql sessionfiles
   # Should should you "ok / ---- / hello"; if it gives an error then something is wrong.

   # Load the database structure (run this from the session-file-server dir):
   psql -f schema.pgsql sessionfiles

   # The 'sessionfiles' database is now ready to go.
   ```

4. Copy `config.py.sample` to `config.py` and edit as needed.  In particular you'll need to edit the
   `pgsql_connect_opts` variable to specify database connection parameters.

5. Set up the application to run via wsgi.  The setup I use is:

   1. Install `uwsgi-emperor` and `uwsgi-plugin-python3`

   1. Configure it by adding `cap = setgid,setuid` and `emperor-tyrant = true` into
      `/etc/uwsgi-emperor/emperor.ini`
   
   1. Create a file `/etc/uwsgi-emperor/vassals/sfs.ini` with content:

      ```ini
      [uwsgi]
      chdir = /home/YOURUSER/session-file-server
      socket = sfs.wsgi
      chmod-socket = 660
      plugins = python3,logfile
      processes = 4
      manage-script-name = true
      mount = /=fileserver:app

      logger = file:logfile=/home/YOURUSER/session-file-server/sfs.log
      ```

      You will need to change the `chdir` and `logger` paths to match where you have set up the
      code.
    
6. Run:

   ```bash
   sudo chown YOURUSER:www-data /etc/uwsgi-emperor/vassals/sfs.ini
   ```

   Because of the configuration you added in step 5, the ownership of the `sfs.ini` determines the
   user and group the program runs as.  Also note that uwsgi sensibly refuses to run as root, but if
   you are contemplating running this program in the first place then hopefully you knew not to do
   that anyway.

7. Set up nginx or apache2 to serve HTTP or HTTPS requests that are handled by the file server.
   - For nginx you want this snippet added to your `/etc/nginx/sites-enabled/SITENAME` file
     (SITENAME can be `default` if you will only use the web server for the Session file server).:

     ```nginx
     location / {
         uwsgi_pass unix:///home/YOURUSER/session-file-server/sfs.wsgi;
         include uwsgi_params;
     }
     ```

   - If you prefer to use Apache then you want to use a

     ```apache
     ProxyPass / unix:/home/YOURUSER/session-file-server/sfs.wsgi|uwsgi://uwsgi-session-file-server/
     ```

     directive in `<VirtualHost>` section serving the site.

8. If you want to use HTTPS then set it up in nginx or apache and put the above directives in the
   location for the HTTPS server.  This will work but is *not* required for Session and does not
   enhance the security because requests are always onion encrypted; the extra layer of HTTPS
   encryption adds nothing (and makes requests marginally slower).

9. Restart the web server and UWSGI emperor: `systemctl restart nginx uwsgi-emperor`

10. In the future, if you update the file server code and want to restart it, you can just `touch
    /etc/uwsgi-emperor/vassals/` — uwsgi-emperor watches the files for modifications and restarts
    gracefully upon modifications (or in this case simply touching, which updates the file's
    modification time without changing its content).
