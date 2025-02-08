# proxy_chunk_downloader
A simple multi-threaded, multi-proxy chunked downloader.

### How to use it
- Modify proxies first in downloader.py

```
--p Enable proxy
--n Number of threads (Default 6)
--name File name (Default name in URL)
--v Disable SSL authentication (Default Enable)
python3 downloader.py [download url] --p --n [number of threads] --name [file name]
```
