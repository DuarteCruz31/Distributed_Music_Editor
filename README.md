# Distributed Music Processing Project

This project aims to split music into multiple chunks and process them in parallel. It leverages Python, Flask, Celery, and Redis to distribute and coordinate the processing of music files across multiple workers.

## Installation

1. Make sure you have Python3, pip, and Redis installed on your machine. If you don't, follow these links to install [Python3](https://www.python.org/downloads/), [pip](https://pip.pypa.io/en/stable/installation/), and [Redis](https://redis.io/download).
   
2. Clone this repository to your local machine:

    ```
    git clone https://github.com/yourusername/Distributed_Music_Editor.git
    cd Distributed_Music_Editor
    ```

3. Set up a virtual environment and install the required packages:

    ```
    python3 -m venv venv
    source venv/bin/activate  # For Windows, use `.\venv\Scripts\activate`
    pip install -r requirements.txt
    ```

4. Start the Redis server (used by Celery as a message broker):
    On mac os:
    ```
    brew services start redis
    ```
    On linux:
    ```
    sudo systemctl start redis
    ```
    On Windows:
    ```
    redis-server
    ```

4. Change the Redis Config to your ip address and protected mode to no:
    On mac os:
    ```
    sudo nano /opt/homebrew/etc/redis.conf
    ```
    On linux:
    ```
    sudo nano /etc/redis/redis.conf
    ```
    On Windows:
    ```
    redis-server
    ```

5. Start the Redis server (used by Celery as a message broker):
    On mac os:
    ```
    brew services start redis
    ```
    On linux:
    ```
    sudo systemctl start redis
    ```
    On Windows:
    ```
    redis-server
    ```

6. Start a Celery worker:
    Open in diferent terminals to see the progress

    ```
    ./run_Worker.sh
    ```

## Usage

1. To start the Flask API server, run:

    ```
    python3 api.py
    ```

    The server will start at `http://{your_ip_address}:5000`.

2. To send a file to be processed just upload a file on the button "Choose File" and click on "Upload File" button.

3. 
    To processe the file with the default parameters just click on "Process File" button and choose which instruments you would like the file to have.

The response will contain the progress of the processing, download links for the separated tracks, and the final merged track once processing is complete.

Please note that this project is experimental and not intended for production use.

## License

This project is licensed under the terms of the MIT license. See the [LICENSE](LICENSE) file for details.

## Authors

* [Duarte Cruz](https://github.com/DuarteCruz31)
* [André Oliveira](https://github.com/andreaoliveira9)