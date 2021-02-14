# scrapli replay

Scrapli replay is a set of tools to help you easily test scrapli programs. Scrapli replay contains a pytest plugin 
which can "wrap" your tests that contain scrapli interactions and record and play them back -- this allows you to 
store "cached" test sessions. These cached test sessions can be stored in version control and give you the ability 
to ensure scrapli is behaving as it should even without devices available (such as in your CI setup).

scrapli replay also contains a "collector" and a "server" which allow you to "collect" interactions from live 
devices, and then build mock ssh server(s) that look and feel pretty close to the real deal! Check out the docs for 
more info!
