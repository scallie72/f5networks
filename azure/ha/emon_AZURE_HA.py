#!/usr/bin/python
# F5 Networks - External Monitor: Azure HA
# https://github.com/ArtiomL/f5networks
# Artiom Lichtenstein
# v0.8, 07/08/2016

import json
import os
import requests
from signal import SIGKILL
import socket
from subprocess import call
import sys

# Log level to /var/log/ltm
intLogLevel = 2
strLogID = '[-v0.8.160807-] emon_AZURE_HA.py - '

# Azure RM REST API
class clsAREA:
	def __init__(self):
		self.strCFile = '/shared/tmp/azure/azure_ha.json'
		self.strMgmtURI = 'https://management.azure.com/'
		self.strAPIVer = '?api-version=2016-03-30'

	def funAbsURL(self):
		return self.strMgmtURI, self.strSubID, self.strRGName, self.strAPIVer

	def funURI(self):
		return self.strMgmtURI, self.strAPIVer


objAREA = clsAREA()

# Logger command
strLogger = 'logger -p local0.info '

class clsExCodes:
	def __init__(self):
		self.intArgs = 8
		self.intArmAuth = 4

objExCodes = clsExCodes()


def funLog(intMesLevel, strMessage):
	if intLogLevel >= intMesLevel:
		lstCmd = strLogger.split(' ')
		lstCmd.append(strLogID + strMessage)
		call(lstCmd)


def funARMAuth():
	# Azure RM OAuth2
	global objAREA
	if not os.path.isfile(objAREA.strCFile):
		funLog(1, 'Credentials file: %s is missing!' % objAREA.strCFile)
		return 3

	try:
		with open(objAREA.strCFile, 'r') as f:
			diCreds = json.load(f)
		objAREA.strSubID = diCreds['subID']
		objAREA.strRGName = diCreds['rgName']
		strTenantID = diCreds['tenantID']
		strAppID = diCreds['appID']
		strPass = diCreds['pass']
		strEndPt = 'https://login.microsoftonline.com/%s/oauth2/token' % strTenantID
	except Exception as e:
		funLog(1, 'Invalid credentials file: %s' % objAREA.strCFile)
		return 2

	# Bearer token
	objPayload = { 'grant_type': 'client_credentials', 'client_id': strAppID, 'client_secret': strPass, 'resource': objAREA.strMgmtURI }
	try:
		objAuthResp = requests.post(url=strEndPt, data=objPayload)
		dicAJSON = json.loads(objAuthResp.content)
		if 'access_token' in dicAJSON.keys():
			objAREA.strBearer = dicAJSON['access_token']
			return 0

	except requests.exceptions.RequestException as e:
		funLog(2, str(e))
	return 1


def funLocIP(strRemIP):
	# Get local private IP
	objUDP = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	objUDP.connect((strRemIP, 0))
	return objUDP.getsockname()[0]


def funCurState(strLocIP):
	funLog(2, 'Current local Private IP: %s, Resource Group: %s' % (strLocIP, objAREA.strRGName))
	# Construct loadBalancers URL
	strURL = '%ssubscriptions/%s/resourceGroups/%s/providers/Microsoft.Network/loadBalancers%s' % objAREA.funAbsURL()
	try:
		# Get LBAZ JSON
		objStatResp = requests.get(strURL, headers = { 'Authorization': 'Bearer %s' % objAREA.strBearer }) 
		dicSJSON = json.loads(objStatResp.content)
		# Extract backend IP ID ([1:] at the end removes the first "/" char)
		strBEIPURI = dicSJSON['value'][0]['properties']['backendAddressPools'][0]['properties']['backendIPConfigurations'][0]['id'][1:]
		objStatResp = requests.get('%sstrBEIPURI%s' % objAREA.funURI(), headers = { 'Authorization': 'Bearer %s' % objAREA.strBearer })
		print objStatResp.content
	except Exception as e:
		funLog(2, str(e))


def funFailover():
	funLog(1, 'Azure failover...')


def main():
	if len(sys.argv) < 3:
		funLog(1, 'Not enough arguments!')
		sys.exit(objExCodes.intArgs)

	# Remove IPv6/IPv4 compatibility prefix (LTM passes addresses in IPv6 format)
	strRIP = sys.argv[1].strip(':f')
	strRPort = sys.argv[2]
	# PID file
	strPFile = '_'.join(['/var/run/', os.path.basename(sys.argv[0]), strRIP, strRPort + '.pid'])
	# PID
	strPID = str(os.getpid())

	funLog(2, 'PIDFile: %s, PID: %s' % (strPFile, strPID))

	# Kill the last instance of this monitor if hung
	if os.path.isfile(strPFile):
		try:
			os.kill(int(file(strPFile, 'r').read()), SIGKILL)
			funLog(1, 'Killed the last hung instance of this monitor.')
		except OSError:
			pass

	# Record current PID
	file(strPFile, 'w').write(str(os.getpid()))

	# Health monitor
	try:
		objResp = requests.head(''.join(['https://', strRIP, ':', strRPort]), verify = False)
		if objResp.status_code == 200:
			os.unlink(strPFile)
			# Any standard output stops the script from running. Clean up any temporary files before the standard output operation
			funLog(2, 'Peer: %s is up.' % strRIP)
			print 'UP'
			sys.exit()

	except requests.exceptions.RequestException as e:
		funLog(2, str(e))

	# Peer down, ARM action needed
	if funARMAuth() != 0:
		funLog(1, 'ARM Auth Error!')
		os.unlink(strPFile)
		sys.exit(objExCodes.intArmAuth)

	# ARM Auth OK
	funLog(2, 'ARM Bearer: %s' % objAREA.strBearer)

	funCurState(funLocIP(strRIP))
	funFailover()

	os.unlink(strPFile)
	sys.exit(1)

if __name__ == '__main__':
	main()
