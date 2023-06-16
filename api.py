import io
from io import BytesIO
import socket
import os
import json
import uuid
import time
import tempfile
import base64
from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS
import eyed3
from pydub import AudioSegment
from celery import Celery
import redis
import random


def get_internal_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
        s.close()
        return ip_address
    except socket.error:
        return None


ip_address = get_internal_ip()

app = Flask(__name__)
CORS(app, origins="*")

celery = Celery('tasks', broker=f'redis://{ip_address}:6379/0',
                backend=f'redis://{ip_address}:6379/0')

celery.conf.task_acks_late = True
celery.conf.worker_prefetch_multiplier = 1

# initial music data
music_data = {}
# where we begin the celery task
job_data = {}
# where the workers will write the data
Job = {}
# final tracks data, already processed and ready to be disposed to the user
final_tracks = {}
# list of workers
workers = []
# list of completed tasks, so it doesnt write in the file more than once
completed_taks = []
# number of conected workers conected to the broker, in order to divide the audio file
conected_workers = 0
# time when the job was created, so we can update it in website
init_time = {}
# list of all the inserted files so there is no repetition,
file_list = []
# give each task a unique id
task_ids = 1


@app.route('/')
def home():
    return render_template('main.html')


@app.route('/conected_workers', methods=['POST'])
def conected_workers_function():
    global conected_workers
    conected_workers += 1
    return jsonify({'conected_workers': conected_workers})


@app.route('/disconnect_workers', methods=['POST'])
def disconnect_workers():
    global conected_workers
    conected_workers -= 1
    return jsonify({'conected_workers': conected_workers})


def split_mp3(file, music_id):
    audio = AudioSegment.from_file(file)
    os.remove(file)
    duration = round(len(audio) / conected_workers)

    # Calculate the remainder of the total duration divided by the number of workers
    remainder = len(audio) % conected_workers

    # Create the audio chunks
    audio_chunks = [audio[i:i + duration]
                    for i in range(0, len(audio), duration)]

    # If there's a remainder, add it to the last chunk
    if remainder:
        audio_chunks[-1] += audio[duration * conected_workers:]

    print(len(audio_chunks))

    for i, chunk in enumerate(audio_chunks):
        with tempfile.NamedTemporaryFile(suffix=".mp3") as temp:
            chunk.export(temp.name, format="mp3")
            with open(temp.name, 'rb') as f:
                chunk_data = base64.b64encode(f.read()).decode('utf-8')

        job_data[music_id].append({
            'chunk_data': chunk_data,
        })
    return


def merge_worker_tracks(music_id, selected_tracks):
    music_id = int(music_id)
    final_tracks[music_id] = {}
    master_track = None
    for track_name in selected_tracks:
        track_data_list = []
        if music_id in Job:
            # sort worker_data based on worker_id
            sorted_worker_data = sorted(
                Job[music_id], key=lambda x: int(x['job_id'].split('_')[-1]))
            for worker_data in sorted_worker_data:
                if worker_data['track'] == track_name.lower():
                    # Decode the base64 data to binary
                    track_data_bin = base64.b64decode(
                        worker_data['track_data'])
                    track_data_list.append(track_data_bin)

        combined = AudioSegment.empty()
        for track_data in track_data_list:
            track_audio = AudioSegment.from_wav(BytesIO(track_data))
            combined += track_audio

        # Save combined tracks to the dictionary as AudioSegment object
        final_tracks[music_id][track_name] = combined

        master_track = master_track.overlay(
            combined) if master_track else combined

    # Save the final merged track
    final_tracks[music_id]["Music"] = master_track


def calculate_average_time():
    total_time = 0
    total_size = 0
    total_files = 0

    with open("tempos.txt", "r") as f:
        for line in f:
            parts = line.split(",")
            if len(parts) == 3:
                music_id = parts[0].split(": ")[1]
                completion_time = float(parts[1].split(": ")[1])
                music_size = int(parts[2].split(": ")[1])
                total_time += completion_time
                total_size += music_size
                total_files += 1

    if total_size > 0:
        average_time_per_size = total_time / total_size
        return average_time_per_size
    else:
        return None


@app.route('/api/music', methods=['POST'])
def upload_music():
    file = request.files['file']
    filename = file.filename

    if filename in file_list:
        return jsonify({'error': 'File already uploaded'})

    file_list.append(filename)
    file.save(os.path.join('musics', file.filename))

    if file.filename.split('.')[-1] != 'mp3':
        return jsonify({'error': 'File must be a mp3 file'})

    # tamanho do ficheiro em bytes
    size = os.path.getsize(os.path.join('musics', filename))

    music_id = random.randint(0, 100000000)

    audio_file = eyed3.load(os.path.join('musics', filename))
    if audio_file is None:
        return jsonify({'error': 'Unable to read audio file'})
    if audio_file.tag:
        name = audio_file.tag.title
        band = audio_file.tag.artist
    else:
        name = ""
        band = ""

    music_data[music_id] = {
        'music_name': filename,
        'music_id': music_id,
        'name': name,
        'band': band,
        'size': size,
        'tracks': [
            {
                "name": "Vocals",
                "track_id": 1,
            },
            {
                "name": "Drums",
                "track_id": 2,
            },
            {
                "name": "Bass",
                "track_id": 3,
            },
            {
                "name": "Other",
                "track_id": 4,
            },
        ],
    }

    job_data[music_id] = []
    split_mp3(os.path.join('musics', filename), music_id)

    return jsonify(music_data[music_id])


@app.route('/api/music', methods=['GET'])
def list_music():
    list = []
    for music_id in music_data:
        list.append(music_data[music_id])
    return jsonify(list)


@celery.task(bind=True)
@app.route('/api/music/<music_id>', methods=['POST'])
def process_music(music_id):
    # check if music id exists in music_data
    global task_ids

    # get list of instrument tracks to be processed
    instruments = []

    data = request.json
    for key in data:
        if int(key) == 5:
            continue
        elif int(key) == 1:
            instruments.append("Vocals")
        elif int(key) == 2:
            instruments.append("Drums")
        elif int(key) == 3:
            instruments.append("Bass")
        elif int(key) == 4:
            instruments.append("Other")

    music_id = int(music_id)

    # Error handling
    if music_id not in music_data:
        return jsonify({'error': 'Music id not found'}), 400
    if music_id in final_tracks:
        return jsonify({'error': 'Music is already processed, check the musics page'})
    elif music_id in Job:
        return jsonify({'error': 'Music is already being processed'})

    # change music data to user's needs
    tracks = music_data[music_id]['tracks'].copy()
    for instrument in tracks:
        if instrument['name'] not in instruments:
            music_data[music_id]['tracks'].remove(instrument)

    # Call the process_chunk task for each music chunk
    for worker_id, chunk in enumerate(job_data[music_id]):
        task = celery.send_task('worker.process_chunk', args=[
                                chunk['chunk_data'], music_id, worker_id + 1])
        chunk.update({
            'task_id': task_ids,
            'worker_id': worker_id,
            'celery_task_id': str(task.id),
            "size": len(chunk['chunk_data']),
            'status': 'processing',
            'start_time': time.time(),
            "music_id": music_id,
            'end_time': None
        })
        task_ids += 1

    return jsonify({'message': 'Processing started'}), 200


@app.route('/api/music/<music_id>', methods=['GET'])
def check_status(music_id):
    music_id = int(music_id)

    # check if music id exists in music_data
    if music_id not in music_data:
        return jsonify({'error': 'Music id not found'}), 400

    # check if music id exists in job_data
    if music_id not in job_data:
        return jsonify({'error': 'Music is not being processed'}), 400

    completion_time = None

    tasks = job_data[music_id]
    average_time_per_size = calculate_average_time()
    remaining_size = music_data[music_id]['size']
    TIMEOUT = average_time_per_size * remaining_size * \
        1.5  # se demorar mais que isto, timeout
    for task in tasks:
        task_id = task.get('celery_task_id')
        start_time = task.get('start_time')
        if task_id:
            celery_task = celery.AsyncResult(task_id)
            if celery_task.state == 'SUCCESS':
                print("Task {} completed".format(task_id))
                task['status'] = 'completed'
                task['end_time'] = time.time()

                if task_id not in completed_taks:
                    completion_time = task['end_time'] - task['start_time']

                    with open("tempos.txt", "a") as f:
                        f.write(
                            f"Music ID: {music_id}, Completion Time: {completion_time}, Music Size: {music_data[music_id]['size']}\n")

                completed_taks.append(task_id)

            elif celery_task.state == 'FAILURE':
                print('task failed')
                print(celery_task.traceback)
                task['status'] = 'failure'

                # retry task
                new_task = celery.send_task('worker.process_chunk', args=[
                    task['chunk_data'], music_id, task['worker_id'] + 1])
                task['celery_task_id'] = new_task.id
                task['start_time'] = time.time()

            elif celery_task.state == 'PENDING':
                print('task pending')
                task['status'] = 'processing'

                # Se estiver a demorar muito mais que o esperado manda outra vez, porque significa que o worker morreu
                if start_time and (time.time() - start_time) > TIMEOUT:
                    new_task = celery.send_task('worker.process_chunk', args=[
                        task['chunk_data'], music_id, task['worker_id'] + 1])
                    task['celery_task_id'] = new_task.id
                    task['start_time'] = time.time()
                    init_time[music_id] = time.time()

    all_done = all(task.get('end_time') is not None and task.get(
        'status') == 'completed' for task in tasks)

    print(f"all_done: {all_done}")

    if all_done:
        istrument_tracks = []  # lista de instrumentos com os links para download
        selected_tracks = []  # lista de instrumentos selecionados pelo utilizador
        selected_tracks.append('Music')
        for track in music_data[music_id]['tracks']:
            pre = {
                'name': track['name'],
                'track': f"http://{ip_address}:5000/api/music/{music_id}/{track['name']}/download"
            }
            selected_tracks.append(track['name'])
            istrument_tracks.append(pre)

        merge_worker_tracks(music_id, selected_tracks)

        download_links = []
        for track in selected_tracks:
            download_links.append(
                f"http://{ip_address}:5000/api/music/{music_id}/{track}/download")

        # remover workers
        workers.clear()

        response = {
            'progresso': 0,
            'instruments': istrument_tracks,
            'final': f"http://{ip_address}:5000/api/music/{music_id}/Music/download"
        }

        return jsonify(response), 200

    else:
        if music_id not in init_time:
            init_time[music_id] = time.time()

        elapsed_time = time.time() - init_time[music_id]

        estimated_remaining_time = int(max(
            average_time_per_size * remaining_size - elapsed_time, 0))

        response = {
            'progresso': estimated_remaining_time
        }

        return jsonify(response), 200


@app.route('/api/music/<music_id>/<track_name>/download', methods=['GET'])
def download_track(music_id, track_name):
    music_id = int(music_id)

    if music_id not in final_tracks or track_name not in final_tracks[music_id]:
        return "Track not found", 404

    # Check if the final track is empty
    if len(final_tracks[music_id][track_name]) == 0:
        return "Final track is empty", 500

    # Convert AudioSegment to mp3
    buffer = io.BytesIO()
    final_tracks[music_id][track_name].export(buffer, format="mp3")

    return Response(
        buffer.getvalue(),
        mimetype="audio/mpeg",
        headers={"Content-disposition": f"attachment; filename={track_name}Final.mp3"})


@ app.route('/workers', methods=['POST'])
def add_worker():
    workers.append(request.json.get('worker_id'))
    return jsonify({'message': 'Worker added successfully'}), 200


@ app.route('/processed/<music_id>', methods=['POST'])
def workers_data_setter(music_id):
    music_id = int(request.json.get('music_id'))
    track_data_base64 = request.json.get('track_data')
    track_name = request.json.get('track').capitalize()

    if music_id not in Job:
        Job[music_id] = []

    track_id = None

    for track in music_data[music_id]['tracks']:
        if track['name'] == track_name:
            track_id = track['track_id']
            break

    Job[music_id].append({
        'job_id': request.json.get('worker_id'),
        'track': request.json.get('track'),
        'track_id': track_id,
        'track_data': track_data_base64,
        'size': len(track_data_base64),
        'time': request.json.get('time'),
        'music_id': music_id
    })
    return jsonify({'message': 'Worker data added successfully'}), 200


@ app.route('/workers', methods=['GET'])
def list_workers():
    lst = []
    for worker in workers:
        lst.append(worker)
    return jsonify({'workers': lst})


@ app.route('/job', methods=['GET'])
def list_jobs():
    # meter os task_id todos numa lista e retornar essa lista
    lst = []
    for music_id in job_data:
        for job in job_data[music_id]:
            lst.append(job.get('task_id'))
    return jsonify(lst)


@ app.route('/job/<job_id>', methods=['GET'])
def get_job(job_id):
    replacer = {}
    for music_id in Job:
        for job in Job[music_id]:
            if job.get('job_id') == str(music_id) + "_" + str(job_id):
                track_id = job.get('track_id')
                if track_id is not None:
                    if 'job_id' not in replacer:
                        replacer['job_id'] = job_id
                        replacer['music_id'] = music_id
                        replacer['size'] = job.get('size')
                        replacer['time'] = job.get('time')
                        replacer['track_id'] = [track_id]
                    else:
                        # Adiciona track_id à lista existente
                        replacer['track_id'].append(track_id)
    return jsonify(replacer)


@app.route('/reset', methods=['POST'])
def cleanup():
    # cancel all celery tasks
    for music in job_data:
        for job in job_data[music]:
            task_id = job.get('celery_task_id')
            celery.control.revoke(task_id, terminate=True)

    celery.control.purge()

    # delete all music and job data
    job_data.clear()
    music_data.clear()
    final_tracks.clear()
    Job.clear()
    workers.clear()

    return jsonify({'message': 'Cleanup successful'}), 200


if __name__ == '__main__':
    app.run(host=f"{ip_address}", port=5000, debug=True)
