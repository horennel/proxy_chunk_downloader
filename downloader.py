import os
import threading
import requests
import json
from tqdm import tqdm
import argparse
import time
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def create_chunks(file_size, num_threads):
    base_chunk_size = file_size // num_threads
    remainder = file_size % num_threads

    chunks = []
    start = 0
    for i in range(num_threads):
        end = start + base_chunk_size - 1
        if i < remainder:
            end += 1
        chunks.append({'start': start, 'end': end, 'downloaded': 0})
        start = end + 1

    return chunks


def download_chunk(url, start, end, index, chunk_size, file_name, status, proxy,
                   progress, verify, max_retries=5, retry_delay=60 * 6):
    headers = {'Range': f'bytes={start}-{end}'}
    proxies = {"http": proxy, "https": proxy} if proxy else None
    retries = 0
    while retries < max_retries:
        try:
            response = requests.get(url, headers=headers, proxies=proxies,
                                    stream=True, verify=verify)
            if response.status_code in [200, 206]:
                with open(f"{file_name}.part{index}", "ab") as file:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        file.write(chunk)
                        status[index]['downloaded'] += len(chunk)
                        progress.update(len(chunk))
                        save_status(file_name, status)
                print(f"分片 {index} 下载成功。")
                return
            else:
                print(f"分片 {index} 下载失败。状态码: {response.status_code}")
        except requests.RequestException as e:
            print(f"下载分片 {index} 时发生错误: {e}")
        retries += 1
        print(f"正在重试分片 {index} ({retries}/{max_retries})...")
        time.sleep(2 ** retries)

    print(
        f"分片 {index} 在 {max_retries} 次尝试后仍下载失败。等待 {retry_delay} 秒后重试。")
    time.sleep(retry_delay)
    download_chunk(url, start, end, index, chunk_size, file_name, status, proxy,
                   progress, verify, max_retries, retry_delay)


def merge_chunks(file_name, total_chunks):
    with open(file_name, "wb") as output_file:
        for i in range(total_chunks):
            with open(f"{file_name}.part{i}", "rb") as part_file:
                while True:
                    chunk = part_file.read(1024 * 1024)  # 1MB 一次读取
                    if not chunk:
                        break
                    output_file.write(chunk)
            os.remove(f"{file_name}.part{i}")
    os.remove(f"{file_name}.status")
    print("所有分片合并成功。")


def save_status(file_name, status):
    with open(f"{file_name}.status", "w") as status_file:
        json.dump(status, status_file)


def load_status(file_name):
    if os.path.exists(f"{file_name}.status"):
        with open(f"{file_name}.status", "r") as status_file:
            try:
                return json.load(status_file)
            except json.JSONDecodeError:
                return None
    return None


def extract_file_name(url):
    return url.split('/')[-1]


def multithreaded_download(url, custom_file_name, use_proxy, num_threads=6,
                           verify=True):
    file_name = custom_file_name if custom_file_name else extract_file_name(url)

    proxies = [
        "http://127.0.0.1:6890",
        "http://127.0.0.1:6891",
        "http://127.0.0.1:6892",
        "http://127.0.0.1:6893",
        "http://127.0.0.1:6894",
        "http://127.0.0.1:6895",
        "http://127.0.0.1:6896",
        "http://127.0.0.1:6897",
        "http://127.0.0.1:6898",
        "http://127.0.0.1:6899",
    ] if use_proxy else [None] * num_threads

    response = requests.head(url, verify=verify)
    file_size = int(response.headers['Content-Length'])

    status = load_status(file_name)
    if not status:
        status = create_chunks(file_size, num_threads)

    downloaded_size = sum([s['downloaded'] for s in status])
    progress = tqdm(total=file_size, initial=downloaded_size, unit='B',
                    unit_scale=True, desc=file_name)

    threads = []
    for i in range(num_threads):
        start = status[i]['start'] + status[i]['downloaded']
        end = status[i]['end']
        if start > end:
            continue
        thread = threading.Thread(target=download_chunk, args=(
        url, start, end, i, 1024, file_name, status, proxies[i], progress,
        verify))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    merge_chunks(file_name, num_threads)
    progress.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="多线程文件下载器，支持代理和SSL验证")
    parser.add_argument('url', type=str, help="要下载的文件的URL")
    parser.add_argument('--name', type=str, help="自定义下载文件的名称")
    parser.add_argument('--p', action='store_true', help="使用代理下载")
    parser.add_argument('--n', type=int, default=6, help="使用的下载线程数")
    parser.add_argument('--v', action='store_false',
                        help="禁用SSL验证（默认启用）")
    args = parser.parse_args()

    multithreaded_download(args.url, args.name, args.p, args.n, args.v)
