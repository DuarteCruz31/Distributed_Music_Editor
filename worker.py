import os
import sys
import time
import uuid
import tempfile
import subprocess
import shutil
import base64
from flask import json
import requests
from io import BytesIO
import tempfile
import uuid


import logging
import argparse
import subprocess

from celery import Celery
from celery.signals import worker_shutdown
from celery.signals import worker_process_shutdown

from demucs.apply import apply_model
from demucs.pretrained import get_model
from demucs.audio import AudioFile, save_audio

server_ip = "192.168.1.92"


app = Celery('tasks', broker=f'redis://{server_ip}:6379/0',
             backend=f'redis://{server_ip}:6379/0')

app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1
app.conf.worker_shutdown = "immediate"

initial_response = requests.post(
    f"http://{server_ip}:5000/conected_workers", json={'conected_workers': 1})


class Worker:
    @staticmethod
    def process_audio_data(audio_data_base64, worker_id, music_id):
        tempo_inicial = time.time()
        # check if audio_data_base64 is of correct type (bytes-like object or ASCII string)
        if not isinstance(audio_data_base64, (bytes, str)):
            logging.warning(
                "Invalid audio data: must be a bytes-like object or ASCII string, not 'int'")
            return

        # get the model
        model = get_model(name='htdemucs')
        model.cpu()
        model.eval()

        # Decode the base64 audio data
        try:
            audio_data = base64.b64decode(audio_data_base64)
        except Exception as e:
            logging.warning(f"Failed to decode base64 audio data: {e}")
            return

        try:
            # Create a temporary file with the audio data
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(audio_data)
                tmp_file_name = tmp.name

            # load the audio data from the temporary file
            wav = AudioFile(tmp_file_name).read(
                streams=0, samplerate=model.samplerate, channels=model.audio_channels)
            ref = wav.mean(0)
            wav = (wav - ref.mean()) / ref.std()

            # apply the model
            sources = apply_model(
                model, wav[None], device='cpu', progress=True, num_workers=1)[0]
            sources = sources * ref.std() + ref.mean()

            # store the model
            for source, name in zip(sources, model.sources):
                # Salvar o áudio em um arquivo temporário
                temp_filepath = os.path.join(
                    tempfile.gettempdir(), f"{uuid.uuid4()}.wav")
                save_audio(source, str(temp_filepath),
                           samplerate=model.samplerate)

                # Abrir o arquivo de áudio e ler os dados binários
                with open(temp_filepath, 'rb') as audio_file:
                    audio_data = audio_file.read()

                # Codificar os dados binários em base64
                audio_data_base64 = base64.b64encode(
                    audio_data).decode('utf-8')

                tempo_final = time.time()

                # Dar post das cenas para a API
                response = requests.post(f'http://{server_ip}:5000/processed/{music_id}', json={
                    'worker_id': worker_id,
                    'track': name,
                    'track_data': audio_data_base64,
                    'music_id': music_id,
                    'time': tempo_final - tempo_inicial
                })

                if response.status_code != 200:
                    logging.warning(f"Não deu para meter na api dos workers")
                else:
                    logging.info(
                        f"Arquivo de áudio enviado com sucesso para a API")
        except Exception as e:
            logging.warning(f"Failed to process audio data: {e}")
            return
        finally:
            # Remove the temporary file
            if os.path.isfile(tmp_file_name):
                os.remove(tmp_file_name)


@app.task(bind=True)
def process_chunk(self, chunk_data, music_id, id):
    # Register this worker in the API
    print("Processing chunk")
    logging.info(f"Processing chunk {id} of music {music_id}")
    logging.info(f"Chunk data: {len(chunk_data)}")
    worker_id = f"{music_id}_{id}"
    response = requests.post(
        f'http://{server_ip}:5000/workers', json={'worker_id': worker_id})

    if response.status_code != 200:
        logging.warning(
            f"Failed to register worker {worker_id}: {response.text}")
        return

    Worker.process_audio_data(
        chunk_data, worker_id, music_id)
    return f"{worker_id}"


@worker_process_shutdown.connect
def shutdown_notice(sender, **kwargs):
    print("Worker is being shut down...")
    requests.post(
        f"http://{server_ip}:5000/disconnect_workers", json={'conected_workers': -1})
