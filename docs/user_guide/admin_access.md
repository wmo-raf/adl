# Access the Admin Interface

The admin interface can be accessed at `http://<ip_or_domain>:<ADL_WEB_PROXY_PORT>`.

Replace `<ip_or_domain>` with the IP address or domain name of the machine where the application is running and
`<ADL_WEB_PROXY_PORT>` with the port number as set in the `.env` file.

For example, if the IP address of the machine is set as `127.0.0.1` and the port as `8000`, you can access the admin
through `http://127.0.0.1:8000`. If the port is set as `80`, you can access the admin directly
through `http://127.0.0.1`.

Below is how the admin interface will look when first accessed.

![Admin Dashboard](../_static/images/user/dashboard.png)