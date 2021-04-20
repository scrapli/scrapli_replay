# Project Details

## What is scrapli replay

scrapli replay is a set of tools to help you test scrapli programs more easily. scrapli replay is very heavily 
influenced by the [`VCR.py`](https://vcrpy.readthedocs.io/en/latest/) library, and the associated pytest plugin 
[pytest_vcr](http://pytest-vcr.readthedocs.io/en/latest/). scrapli replay's primary function is to provide a similar 
testing experience for Telnet/SSH/NETCONF programs as these great tools do for HTTP/HTTPs programs.

scrapli replay also contains tooling to help you "dynamically" build "interactive" SSH servers based on real life 
SSH devices -- again, the purpose of this is to help you more easily test things offline, in CI environments, or 
just have something safe to mess around with. There are quotes around "dynamically" and "interactive" as these are 
perhaps loaded terms! "dynamically" meaning the scrapli replay "collector" can connect to, and collect output from a 
real life SSH server. The scrapli replay "server" is then able to load the collected data and operate as a mock SSH 
server -- any commands that you collected are able to be "played back" in an "interactive" fashion. Check out the 
basic usage guide for more info -- and some examples -- to make things more clear! 


## Related Scrapli Libraries

scrapli replay is really just test tooling built around the scrapli family of libraries -- and as such is not really 
*directly* useful for connecting to devices and getting things done. If you are interested in getting things done, 
check out the related scrapli libraries below:

- [scrapli](/more_scrapli/scrapli)
- [scrapli_netconf](/more_scrapli/scrapli_netconf)
- [scrapli_community](/more_scrapli/scrapli_community)
- [scrapli_cfg](/more_scrapli/scrapli_cfg)
- [nornir_scrapli](/more_scrapli/nornir_scrapli)
