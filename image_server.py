from PIL import Image
import numpy as np
import torch
import io
import hashlib
import asyncio
import websockets
import threading
import urllib.parse

server = None
host = '0.0.0.0'
port = 5000
image_data = None
image_queue = asyncio.Queue()

MAX_BUFFER_SIZE = 2 ** 20  # 1 MB
RETRY_DELAY = 0.5  # Seconds

async def send_images(websocket):
    global image_queue

    while True:
        if not image_queue.empty():
            try:
                data = await image_queue.get()

                if data is not None and isinstance(data, (bytes, bytearray)):
                    if len(data) < MAX_BUFFER_SIZE:
                        print(f"Sending image of size {len(data)} bytes")
                        await websocket.send(data)
                    else:
                        print("Write buffer full, waiting before sending more data")
                        await asyncio.sleep(RETRY_DELAY)  # Adjust delay as needed
                else:
                    print("Data is either None or not a bytes-like object, not sending.")

                image_queue.task_done()
            except websockets.exceptions.ConnectionClosed as e:
                print(f"WebSocket connection closed normally: {e}")
                break  # Exit the loop as the closure is normal
            except websockets.exceptions.ConnectionClosedError as e:
                print(f"WebSocket connection closed with error: {e}")
                break
            except Exception as e:
                print(f"Error sending image: {e}")
                await asyncio.sleep(RETRY_DELAY)  # Implement retry delay logic
        else:
            await asyncio.sleep(0.005)

def is_valid_image(data):
    try:
        # Open the image data using a BytesIO stream
        with Image.open(io.BytesIO(data)) as img:
            # Perform optional checks here
            # For example, to check for a specific format:
            if img.format != 'JPEG':
                 return False

            # Check if the image can be read without errors
            img.verify()  # This will raise an exception if the image is not valid

        # If no exception was raised, the image is valid
        return True

    except Exception as e:
        print(f"Invalid image data: {e}")
        return False

async def receive_images(websocket):
    global image_data

    while True:
        try:
            message = await websocket.recv()

            if message is not None and isinstance(message, (bytes, bytearray)):
                print(f"Received image of size {len(message)} bytes")
                if is_valid_image(message):  # Implement your image validation logic
                    data = io.BytesIO(message)
                    image_data = data  # Make sure to manage older data
                else:
                    print("Invalid image data received")
            else:
                print("Message is either None or not a bytes-like object, not processing.")
        except websockets.exceptions.ConnectionClosed as e:
                print(f"WebSocket connection closed normally: {e}")
                break  # Exit the loop as the closure is normal
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"WebSocket connection closed with error: {e}")
            break
        except Exception as e:
            print(f"Error receiving image: {e}")
            # Implement retry or error handling logic as needed

async def websocket_handler(websocket, path):
    print(f"New WebSocket connection established from {websocket.remote_address}")

    send_task = asyncio.create_task(send_images(websocket))
    receive_task = asyncio.create_task(receive_images(websocket))

    await asyncio.gather(send_task, receive_task)

    print(f"WebSocket connection closed from {websocket.remote_address}")

def start_async_loop():
    global server, host, port

    print(f"\n\nStarted server on {host}:{port}\n")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = websockets.serve(websocket_handler, host, port)
    loop.run_until_complete(server)
    loop.run_forever()

def start_server_in_thread():
    thread = threading.Thread(target=start_async_loop)
    thread.daemon = True  # Optionally make the thread a daemon
    thread.start()

start_server_in_thread()

class LoadServerImage:

    @classmethod
    def INPUT_TYPES(self):
        return {
                "required": {
                    "server_port": ("INT", {"default": port, "min": port, "max": port, "multiline": False}), 
                }
            }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "load_image"
    
    CATEGORY = "Image Server"

    def load_image(self, server_port):
        global image_data

        if image_data is None:
            print("No image data received yet")
            black_image_tensor = torch.zeros(1, 1, 3)
            return (black_image_tensor, )

        try:
            image = Image.open(image_data)
            image = image.convert('RGB')
            image_np = np.array(image).astype(np.float32) / 255.0
            image_tensor = torch.from_numpy(image_np)[None,]
            return (image_tensor, )
        except Exception as e:
            print(f"Failed to load image: {e}")
            black_image_tensor = torch.zeros(1, 1, 3)
            return (black_image_tensor, )
        
    @classmethod
    def IS_CHANGED(self, server_port):
        # DOESN'T WORK
        global server

        server.stop()  # stop the server
        server.port = server_port  # change the port
        server.start()  # start the server again
        
        print(f"Changed server port to {server_port}")

        m = hashlib.sha256()
        m.update(server_port)
        return m.digest().hex()

class SendServerImage:

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"images": ("IMAGE",)}}

    RETURN_TYPES = ()
    FUNCTION = "send_images"
    OUTPUT_NODE = True
    CATEGORY = "Image Server"

    def send_images(self, images):
        global server, image_queue

        if server is None:
            raise ValueError("Server cannot be None")

        results = []
        for image in images:
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
            byte_arr = io.BytesIO()
            img.save(byte_arr, format='PNG')
            image_bytes = byte_arr.getvalue()
            asyncio.run(image_queue.put(image_bytes))

            # results.append(image_bytes)

        return {"ui": {"images": results}}
    
NODE_CLASS_MAPPINGS = {
    "LoadServerImage": LoadServerImage,
    "SendServerImage": SendServerImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadServerImage": "Load Server Image",
    "SendServerImage": "Send Server Image"
}
