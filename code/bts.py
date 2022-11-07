import hashlib
from colorama import Fore
import socket
import threading
from Crypto.Cipher import AES
from Crypto.Util.number import long_to_bytes, bytes_to_long
import os
from Crypto.Util.Padding import pad, unpad
import time
from my_utils import send_value, recv_value, is_auth_valid, reset_cipher

NONCE_LEN = 11
TIME_THRESHOLD = 5
KEY_LEN = 16
TOKEN_LEN = 2
ACK_LEN = 2
ENC_PLUS_TAG_LEN = 32
BLOCK_LEN = 16
LOCALHOST = "127.0.0.1"
N_PORT = 8082
PORT_LEN = 4
SECRET_SEQ = b'X'  # pre-established secret sequence for ack computation
# the base station has a dictionary containing for each cluster head: the id (port),
# the pre-shared key and a list of neighbors
# TODO add tokens for update
# TODO consider the case of many neighbors for the perfomance evaluation
NODE_DICT = {b'8081': [b'0123456789abcdef', [b'8082', b'8083', b'8084', b'8085', b'8086', b'8087', b'8088', b'8089', b'8090', b'8091']],
             b'8082': [b'fedcba9876543210', [b'8081']],
             b'8083': [os.urandom(16), [b'8081']],
             b'8084': [os.urandom(16), [b'8081']],
             b'8085': [os.urandom(16), [b'8081']],
             b'8086': [os.urandom(16), [b'8081']],
             b'8087': [os.urandom(16), [b'8081']],
             b'8088': [os.urandom(16), [b'8081']],
             b'8089': [os.urandom(16), [b'8081']],
             b'8090': [os.urandom(16), [b'8081']],
             b'8091': [os.urandom(16), [b'8081']]}


def kerberos_protocol(server):

    # receive client ID and getting key and neighbors
    client_id = recv_value(server.csocket, PORT_LEN)
    print(Fore.RED+"Client ID: ", client_id, Fore.WHITE)
    client_params = NODE_DICT[client_id]
    k_a = client_params[0]
    neighbors = client_params[1]
    # TODO nonces update
    nonce = os.urandom(NONCE_LEN)
    cipher = AES.new(k_a, AES.MODE_CCM, nonce)

    # send session key
    s_key = os.urandom(KEY_LEN)
    if not __debug__:
        print('Session key: ', s_key)
    msg, mac = cipher.encrypt_and_digest(s_key)
    print('sending session key...')
    send_value(server.csocket, msg+mac+nonce)

    # receive authenticator
    data = recv_value(server.csocket, BLOCK_LEN*2+NONCE_LEN)
    data, nonce = data[:-NONCE_LEN], data[-NONCE_LEN:]
    s_cipher = reset_cipher(s_key, nonce)
    auth = s_cipher.decrypt_and_verify(data[:BLOCK_LEN], data[BLOCK_LEN:])
    auth = bytes_to_long(unpad(auth, BLOCK_LEN))

    print(Fore.RED+"Authenticator: ", auth, Fore.WHITE)
    if not is_auth_valid(auth):
        print("ERROR")
        exit(0)
        # handle error

    # send IDs and keys
    s_cipher, nonce = reset_cipher(s_key)  # reset cipher
    if not __debug__:
        print(neighbors)
    keys = []
    keys.append(b'1'*KEY_LEN)
    for i in range(9):
        keys.append(os.urandom(KEY_LEN))
    if not __debug__:
        print(keys)
    data = b''.join(neighbors)+b''.join(keys)

    msg, mac = s_cipher.encrypt_and_digest(pad(data, BLOCK_LEN))
    print('sending ids and keys...')
    send_value(server.csocket, msg+mac+nonce)
    print("Client at ", clientAddress, " disconnected...")

    # wait input before wake up
    input()

    # wake up neighbor
    nsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    nsocket.connect((LOCALHOST, N_PORT))

    print('Waking up ', LOCALHOST, ':', N_PORT)
    # token of the neghbor TODO implement a table for all neighbors? TODO Implement token update?
    # send token
    n_token_key = b'a'*KEY_LEN
    hasher = hashlib.sha256()
    hasher.update(n_token_key+str(N_PORT).encode())
    n_token = hasher.digest()[:TOKEN_LEN]
    send_value(nsocket, n_token)

    # receive ack
    ack = recv_value(nsocket, 2)
    print(Fore.BLUE+"ACK: ", ack, Fore.WHITE)
    hasher = hashlib.sha256()
    hasher.update(n_token+SECRET_SEQ)
    expected_ack = hasher.digest()[:ACK_LEN]
    if ack != expected_ack:
        print("ACK not correct")
        exit(0)

    # send ticket and auth
    k_ab = keys[0]
    print('Sending ticket and auth')
    ticket = pad(b'8081'+k_ab, BLOCK_LEN)
    # take the key of the neighbor
    k_b = NODE_DICT[neighbors[0]][0]
    t_cipher, nonce = reset_cipher(k_b)
    auth = pad(long_to_bytes(time.time()), BLOCK_LEN)
    ticket, tag = t_cipher.encrypt_and_digest(ticket+auth)
    send_value(nsocket, ticket+tag+nonce)

    # receive ack
    data = recv_value(nsocket, BLOCK_LEN*2+NONCE_LEN)
    data, nonce = data[:-NONCE_LEN], data[-NONCE_LEN:]
    a_cipher = reset_cipher(k_ab, nonce)
    ack = a_cipher.decrypt_and_verify(data[:BLOCK_LEN], data[BLOCK_LEN:])
    ack = bytes_to_long(unpad(ack, BLOCK_LEN))
    print(Fore.BLUE+"Authenticator + 1: ", ack, Fore.WHITE)
    auth = bytes_to_long(unpad(auth, BLOCK_LEN))
    if ack != (auth+1):
        print('Wrong authenticator')
        exit(0)

    print('Connection with ', LOCALHOST, ':', N_PORT, ' closed')
    nsocket.close()


class ClientThread(threading.Thread):
    def __init__(self, clientAddress, clientsocket):
        threading.Thread.__init__(self)
        self.csocket = clientsocket
        # crypto settings
        self.node_dict = {}

    def run(self):
        print("Connection from : ", clientAddress)
        kerberos_protocol(self)
        print()


# socket settings
LOCALHOST = "127.0.0.1"
PORT = 8080
bts = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
bts.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
bts.bind((LOCALHOST, PORT))


print("\nBTS started\nWaiting for Cluster Head request..")
while True:
    bts.listen(1)
    clientsock, clientAddress = bts.accept()
    newthread = ClientThread(clientAddress, clientsock)
    newthread.start()
