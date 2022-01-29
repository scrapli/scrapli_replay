# Changelog


## 2022.01.30

- Dropped Python3.6 support as it is now EOL! Of course, scrapli probably still works just fine with 3.6 (if you 
  install the old 3.6 requirements), but we won't test/support it anymore.
- Some typing cleanup based on updated asyncssh typing additions.
- Fixed poorly used private attribute (on my end) causing scrapli-replay to break with asyncssh 2.9 strictly due to 
  a typing issue.

## 2021.02.28

- Initial release
