import base64
import hashlib
import hmac
import json
import os
from hashlib import sha1
from urllib.parse import urlparse
from urllib.request import urlopen

import pem
import six
from django.utils.encoding import smart_bytes
from OpenSSL import crypto

file_path = os.path.join(os.getcwd(),'SimpleNotificationService-e372f8ca30337fdb084e8ac449342c77.pem')
f = open(file_path, "r")
cert = f.read()
certificate_pem=crypto.load_certificate(crypto.FILETYPE_PEM, cert)
pub_key_obj = certificate_pem.get_pubkey()
pub_key = crypto.dump_publickey(crypto.FILETYPE_PEM,pub_key_obj)
priv_key = crypto.dump_privatekey(crypto.FILETYPE_PEM,pub_key_obj)


data = {
  "Type" : "SubscriptionConfirmation",
  "MessageId" : "334fa09c-cfa2-465c-82aa-733848bece90",
  "Token" : "2336412f37fb687f5d51e6e241d164b05333037a74406d8dba969d354ea74d83709cd31e96da0cd0a3a0ee0e27b1327ffe742b592fbd94724bef9e6b34405815f36381b22a27ba71d23d5e9219ecdc786e8d9a32d028cf2c433403ac5f19a911c8248f581af32bb9459f6f5318aa707cb71f43438cdb0c84fd169d8b803ba5f1",
  "TopicArn" : "arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes",
  "Message" : "You have chosen to subscribe to the topic arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes.\nTo confirm the subscription, visit the SubscribeURL included in this message. Try encode £.",
  "SubscribeURL" : "https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription&TopicArn=arn:aws:sns:us-east-1:250214102493:Demo_App_Unsubscribes&Token=2336412f37fb687f5d51e6e241d164b05333037a74406d8dba969d354ea74d83709cd31e96da0cd0a3a0ee0e27b1327ffe742b592fbd94724bef9e6b34405815f36381b22a27ba71d23d5e9219ecdc786e8d9a32d028cf2c433403ac5f19a911c8248f581af32bb9459f6f5318aa707cb71f43438cdb0c84fd169d8b803ba5f1",
  "Timestamp" : "2013-10-18T15:45:00.871Z",
  "SignatureVersion" : "1",
  "Signature" : "bfEXuIHh26xHeN9p2buadZl5U7mbj+lwf+3t03Cuxw6NLLgd48e+ij6EuZNmnRTWqGvgV/hkGiIYZtzk5g9dfKeSdYuH8YOGU8Z8OsNuo0Y5XoHxTfMHZAimgO/YjK/VwR+Umpop1Ov4+zIlCNUCDXLOSv7JMVqwQGwnMOYxzh2OHCfLJkoAYtCfPkXLdMGxwMDzwWtVWBwjnG4DwvgJFlNV2jdZrC6NPKtyz8YNbpBrW5yR20jShWS54unNXqx/8Y8fXq4QpFpjX7CC2DHTbhU25APamayN1nZYFO6V+3gaKwXU46X++fYU+8Ryr7lbTHKJ8xp6x5XCMu4hxXisAQ==",
  "SigningCertURL" : "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-e372f8ca30337fdb084e8ac449342c77.pem"
}
# 
# 
# 
# def sign(key, msg):
#     return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
# 
# def getSignatureKey(key, dateStamp, regionName, serviceName):
#     kDate = sign(("AWS4" + key).encode("utf-8"), dateStamp)
#     kRegion = sign(kDate, regionName)
#     kService = sign(kRegion, serviceName)
#     kSigning = sign(kService, "aws4_request")
#     return kSigning

# getSignatureKey(key, dateStamp, regionName, serviceName)

hash_format = u'''Message
{Message}
MessageId
{MessageId}
SubscribeURL
{SubscribeURL}
Timestamp
{Timestamp}
Token
{Token}
TopicArn
{TopicArn}
Type
{Type}
'''

print(hash_format.format(**data))
 
digest = 'sha1'
print(pub_key_obj._pkey)
print(pub_key)

print(priv_key)
# 
signature = crypto.sign(pub_key_obj, (hash_format.format(**data)).encode('utf-8'), digest)
# 
print(signature)






a = "\u2019"
print('Input:', a)

try:
  print('Encoded result:', a.encode('utf-8'))
except:
  print('Cant encode using utf-8')

try:
  print('Encoded result:', a.encode('latin-1'))
except:
  print('Cant encode using latin-1')

try:
  print('Encoded result:',six.b(a))
except:
  print('Cant encode using six')
