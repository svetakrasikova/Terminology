# -*- coding: utf-8 -*-
#####################
#
# © 2013–2015 Autodesk Development Sàrl
#
# Created in 2013 by Alok Goyal
#
# Changelog
# !!! Subsequent changes tracked on GitHub only !!!
#
# v3.4.1	Modified on 26 Feb 2015 by Mohamed Marzouk
# Changing the cursor.execute() so as to make it secure and disable sql injection
#
# v3.4		Modified on 30 Jan 2015 by Samuel Läubli
# Term translations are now pushed to Solr/NeXLT as soon as they are approved. Translations from the Term Translation
# Central are indexed with the "resource"="Terminology" attribute in Solr.
#
# v3.3.1	Modified on 28 Jan 2015 by Ventsislav Zhechev
# Improved user-friendliness during search, by maintaining the selected search options after performing the search.
#
# v3.3		Modified on 27 Jan 2015 by Ventsislav Zhechev
# Now we support term search functionality.
#
# v3.2.2	Modified on 27 Jan 2015 by Ventsislav Zhechev
# Modified the sorting order for term lists created by product/language combination to be alphabetic by source term.
#
# v3.2.1	Modified on 16 Jan 2015 by Ventsislav Zhechev
# Fixed a bug with the exception handling during MT processing.
#
# v3.2		Modified on 14 Jan 2015 by Ventsislav Zhechev
# The servide will now send term contexts to the MT Info Service for translation with the current MT engines.
#
# v3.1.7	Modified on 12 Jan 2015 by Ventsislav Zhechev
# Small modifications to debug output.
#
# v3.1.6	Modified on 21 Aug 2014 by Ventsislav Zhechev
# Fixed a bug where redicrects would point to the wrong URL.
# Fixed a bug where a TBX for all languages and all products could not be exported.
#
# v3.1.5	Modified on 12 Aug 2014 by Ventsislav Zhechev
# Modified to use aliases for staging and production MySQL servers.
#
# v3.1.4	Modified on 27 May 2014 by Ventsislav Zhechev
# Fixed a bug where user names weren’t SQL-escaped, causing crashes.
#
# v3.1.3	Modified on 21 May 2014 by Ventsislav Zhechev
# Updated to connect to new MySQL setup.
#
# v3.1.2	Modified on 24 Mar 2014 by Ventsislav Zhechev
# Fixed a bug where login would fail for users with non-ascii characters in their username.
#
# v3.1.1	Modified on 17 Jan 2014 by Ventsislav Zhechev
# Fixed a bug where the error stream redirection was using the wrong App name in production.
#
# v3.1		Modified on 25 Nov 2013 by Ventsislav Zhechev
# Made it simpler to deploy from staging to production.
# Added a method that allows AJAX calls to check if a user is still authenticated in the system.
#
# v3.0		Modified on 18 Nov 2013 by Ventsislav Zhechev
# First production-ready version
#
# v2.5		Modified on 01 Nov 2013 by Ventsislav Zhechev
# Updated to fit the final database structure.
# Introduced handling of user logins.
# Database data can be viewed on linked pages.
#
# v2.1		Modified on 22 Oct 2013 by Ventsislav Zhechev
# The results of the term extrction process are now written to a MySQL database.
# The availability of the requested Content Type, Product Code and Language are checked against the data in a MySQL database.
#
# v2			Modified on 15 Oct 2013 by Ventsislav Zhechev
# Converted to queue-based processing of incomming requests with a single thread dedicated to term extraction and database interaction.
#
# v1			Modified by Alok Goyal, Mirko Plitt
# Original version.
#
#####################

isStaging = True

dbName = "Terminology"
if (isStaging):
	dbName +="_staging"
	from Terminology_staging import Terminology_staging as app, Extractor
	app.config['STAGING'] = True
else:
	from Terminology import Terminology as app, Extractor
	app.config['STAGING'] = False


class RedirectStderr:
	def write(self, string):
		app.logger.ERROR(string)

class RedirectStdout:
	def write(self, string):
		app.logger.ERROR(string)

import sys
sys.stderr = RedirectStderr()
sys.stdout = RedirectStdout()

from flask import request, session, render_template, redirect, make_response
from forms import LoginForm
import json
import os, re
from xml.sax.saxutils import escape
import pymysql
import urllib2, pyDes
from pyDes import triple_des
from datetime import timedelta
import traceback

import socket
import select

import threading
import Queue

import md5
import requests

mainKey = "\xE7\xE4\x81\x29\xA1\xE3\x45\x38\xF8\x3A\xDE\x13\x15\xEB\x70\xCE\x5A\x1F\xE3\x31\x00\x00\x00\x00"
mainIV = "\xDA\x39\xA3\xEE\x5E\x6B\x4B\x0D"

exitFlag = False

logger = app.logger

def connectToDB():
	if isStaging:
		return pymysql.connect(host="aws.stg.mysql", port=3306, user="root", passwd="Demeter7", db=dbName, charset="utf8")
	else:
		return pymysql.connect(host="aws.prd.mysql", port=3306, user="root", passwd="Demeter7", db=dbName, charset="utf8")
	
class termHarvestThread (threading.Thread):
	def __init__(self, threadID):
		threading.Thread.__init__(self)
		self.threadID = threadID
		logger.debug(u"Initialising term extraction facilities…".encode('utf-8'))
		Extractor.__debug_on__ = True
		pathname = os.path.dirname(sys.argv[0])
		if not pathname:
			pathname = "."
		if not os.path.exists(pathname + "/" + dbName + "/auxiliaryData/unwords"):
			pathname = "/usr/lib/cgi-bin"
		Extractor.init(dict(
			adskCorpusRoot = pathname + "/" + dbName + "/auxiliaryData/taggerCorpus",
			adskUnwordsRoot = pathname + "/" + dbName + "/auxiliaryData/unwords",
			))
		Extractor.loadAuxiliaryData()
		logger.debug(u"Training POS tagger…".encode('utf-8'))
		try:
			if isStaging:
				Extractor.trainPOSTagger(0)
			else:
				Extractor.trainPOSTagger(0)
		except Exception, e:
			logger.debug("Could not train POS tagger!".encode('utf-8'))
			logger.debug(traceback.format_exc())
			raise
		logger.debug("Initialised!".encode('utf-8'))
	def run(self):
		global exitFlag
		logger.debug("Starting thread " + str(self.threadID))
		while not exitFlag:
			try:
				jobID, contentID, products, language, data = jobQueue.get(True, 60)
				logger.debug((u"Processing a job…\nContentID: " + str(contentID) + "; ProductID: " + str(products[0]) + "; LanguageID: " + str(language[0])).encode('utf-8'))
				#process job
				try:
					terms = Extractor.Getterms(data, language[1], products[1], 0)
				except Exception, e:
					logger.debug("Could not extract terms!".encode('utf-8'))
					logger.debug(traceback.format_exc())
					raise
				
				#Machine translation of source contexts
				logger.debug("Processing source contexts through MT")
				contextSet = set()
				#Collect all contexts in a set, so that we don’t translate duplicates
				for term in terms:
					contextSet.update(term[2])
				logger.debug("Found %s contexts for translation" % len(contextSet))
				contextDict = MT(contextSet, language[2])
				
				
				conn = connectToDB()
				cursor = conn.cursor()
#				termCounter = 0
				for term in terms:
#					termCounter = termCounter + 1
#					logger.debug(u"inserting source term %s %s, %s" % (termCounter, term[0], term[1]))
# 					logger.debug("SQL: %s\n" % sql)
					cursor.execute("insert into SourceTerms(Term) values (%s) on duplicate key update ID=last_insert_id(ID)", (term[0],))
					cursor.execute("select last_insert_id()")
					sourceTermID, = cursor.fetchone()
#					logger.debug("SQL: %s\n" % sql)
					cursor.execute("insert into TermTranslations(JobID, SourceTermID, LanguageID, ProductID, GlossID, ContentTypeID, NewTo, DateRequested) values (%s, %s, %s, %s, %s, %s, %s, NULL) on duplicate key update ID=last_insert_id(ID), DateUpdated=CURRENT_TIMESTAMP, ContentTypeID=selectContentTypeID(ContentTypeID, %s)", (jobID, sourceTermID, language[0], products[0][0], products[0][1], contentID, term[1], contentID))
					cursor.execute("select last_insert_id()")
					termTranslationID, = cursor.fetchone()
					sql = "insert into TermContexts(TermTranslationID, ContentTypeID, SourceContext, MTofContext) values "
					dbparams = ()
					for context in term[2]:
						if contextDict[context] == "":
							sql += "(%s, %s, %s, null), "
							dbparams += (termTranslationID, contentID, context)
						else:
							sql += "(%s, %s, %s, %s), "
							dbparams += (termTranslationID, contentID, context, contextDict[context])
					sql = sql[:-2] + " on duplicate key update LastUpdate=NULL, ContentTypeID=selectContentTypeID(ContentTypeID, %s)"
					dbparams += (contentID,)
#					logger.debug("SQL: %s\n" % sql)
					cursor.execute(sql, dbparams)
					
				logger.debug(u"Finished inserting terms, pending DB commit…")
				#finished processing job
				cursor.execute("update PendingJobs set Pending=0, DateProcessed=CURRENT_TIMESTAMP where ID=%s limit 1", (jobID,))
				conn.commit()
				conn.close()
				logger.debug(u"DB commit done!")
				jobQueue.task_done()
			except Queue.Empty:
				pass
		logger.debug("Exiting thread " + str(self.threadID))

def MT(content, language):
	if len(content) == 0:
		return {}
	contentList = list(content)

	mt_socket = None
	MTError = False
	try:
		mt_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		mt_socket.settimeout(6000)
		mt_socket.connect(('10.35.136.43', 2000))
	except Exception, e:
		logger.exception('Could not connect to 10.35.136.43:2000\n"%s"' % e)
		try:
			mt_socket.connect(('10.35.136.43', 2001))
		except Exception, e:
			logger.exception('Could not connect to 10.35.136.43:2001\n"%s"' % e)
			MTError = True

	if MTError:
		emptyMT = [""] * len(contentList)
		return dict(zip(contentList, emptyMT))

	translated = []
	try:
		header = "{targetLanguage => " + language +", translate => " + str(len(contentList)) + "}"
		#	header = "{targetLanguage => " + language +", translate => " + str(len(contentList)) +", product => " + str(product_name) +"}"
		logger.debug("MT request header:\n%s" % header)
		
		send = None
		receive = None
		try:
			send = mt_socket.makefile('w', 0)  # to [w]rite , unbuffered
			try:
				receive = mt_socket.makefile('r', 0)  # to [r]ead , unbuffered
			except:
				send.close()
				raise
				
			# Write strings to MT Info Service
			try:
				send.write(header.encode('utf-8') + "\n")
				for string in contentList:
					send.write(string.encode('utf-8') + "\n")
				
				logger.info("All strings written to: %s:%s" % mt_socket.getpeername())
			except Exception, e:
				logger.debug(traceback.format_exc())
				raise e
					
			# Read translations from MT Info Service
			try:
				ready = select.select([mt_socket], [], [], 300)
				if ready[0]:
					responseHeader = receive.readline().decode('utf-8')
					logger.debug("MT response header:\n%s" % responseHeader)
				else:
					logger.critical("MT Info Service read timeout!")
					raise Exception
				
				MTError = responseHeader[:1] == u""
				for i in range(len(contentList)):
					if MTError:
						translated.append("")
					else:
						ready = select.select([mt_socket], [], [], 600)
						if ready[0]:
							s = receive.readline().decode('utf-8')
						else:
							logger.critical("MT Info Service read timeout!")
							raise Exception
						if s[:1] == u"":
							MTError = True
							translated.append("")
						else:
							translated.append(s.rstrip('\n'))
						
			except Exception, e:
				logger.debug(traceback.format_exc())
				raise e

			logger.info("All Strings received from MT server (%s:%s)" % mt_socket.getpeername())
		except Exception, e:
			logger.fatal(("EXCEPTION WHILE TRANSLATING (%s:%s) " % mt_socket.getpeername()) + "%s" % e)
			logger.exception(e)
			MTError = True
		finally:
			send.close()
			receive.close()
				
	except:
		logger.debug(traceback.format_exc())
		MTError = True
	finally:
		logger.info(u"Closing MT server socket…")
		try:
			mt_socket.close()
		except Exception, e:
			MTError = True
			logger.critical(e)

	if MTError:
		logger.debug("We have an MT error!")
		emptyMT = [""] * len(contentList)
		return dict(zip(contentList, emptyMT))
	else:
		logger.debug("MT went fine")
		return dict(zip(contentList, translated))
				
def isSupportedContent(content, conn):
	if content == "Both":
		return None
	cursor = conn.cursor()
	cursor.execute("select ID from ContentTypes where ContentType=%s limit 1", (content,))
	result = cursor.fetchone()
	if not result:
		return None
	return result[0]

def isSupportedProduct(prod, conn):
	cursor = conn.cursor()
	cursor.execute("select ProductCode from Products where GlossID = (select GlossID from Products where ProductCode = %s)", (prod,))
	result = cursor.fetchall()
	if not result:
		return None
	cursor.execute("select ID, GlossID from Products where ProductCode = %s limit 1", (prod,))
	return (cursor.fetchone(), [p[0] for p in result])

def isSupportedLanguage(lang, conn):
	cursor = conn.cursor()
	cursor.execute("select ID, LangCode3Ltr, LangCode2Ltr from TargetLanguages where LangCode2Ltr = %s limit 1", (lang,))
	result = cursor.fetchone()
	if not result:
		cursor.execute("select ID, LangCode3Ltr, LangCode2Ltr from TargetLanguages where LangCode3Ltr = %s limit 1", (lang,))
		result = cursor.fetchone()
		if not result:
			return None
	return result
	
def recentLanguages(cursor):
	cursor.execute("select ID, LangName from TargetLanguages where LastUsed is not null order by LastUsed desc limit 5")
	return cursor.fetchall()

def recentProducts(cursor):
	cursor.execute("select ID, ProductCode from Products where LastUsed is not null order by LastUsed desc limit 15")
	return cursor.fetchall()

def latestJobs(cursor):
	cursor.execute("select JobID, concat_ws(', ', ProductCode, LangCode3Ltr, ContentType) as JobString from JobList order by DateProcessed desc limit 20")
	return cursor.fetchall()


@app.route('/termharvest/', methods=['POST'])
def termharvest():
	global threads
	#set default code 204 which will be returned in case every thing went fine
	respCode = 204
	#set message as success which will be returned until overridden
	respStr = "Started task in background"
	
	requestContent = None
	try:
		requestContent = request.get_json(cache=True)
	except:
		logger.error("Could not handle JSON data!")
		return ("Could not parse JSON data", 400)
	contentType = requestContent['contentType']
	productCode = requestContent['productCode']
	lang = requestContent['language']
	
	conn = connectToDB()
	cursor = conn.cursor()
	
	logger.debug((u"Checking if the requested content type is supported… (" + contentType + ")").encode('utf-8'))
	contentID = isSupportedContent(contentType, conn)
	if not contentID:
		respCode = 400
		respStr = "Unsupported content type: " + contentType + ". Choose one of these:"
		cursor.execute("select ContentType from ContentTypes where ContentType != 'Both'")
		for contentType in cursor:
			respStr = respStr + " " + contentType[0]
		return (respStr, respCode)
	else:
		logger.debug("Will use the following content ID: " + str(contentID) + "")

	logger.debug((u"Checking if the requested product is supported… (" + productCode + ")").encode('utf-8'))
	prods = isSupportedProduct(productCode, conn)
	if not prods:
		respCode = 400
		respStr = "Unsupported product code: " + productCode + ". Choose one of these:"
		cursor.execute("select ProductCode from Products")
		for product in cursor:
			respStr = respStr + " " + product[0]
		return (respStr,respCode)
	else:
		logger.debug("Will check against following product codes:")
		logger.debug(" ".join(prods[1]))
			
	logger.debug((u"Checking if the requested language is supported… (" + lang + ")").encode('utf-8'))
	language = isSupportedLanguage(lang, conn)
	if not language:
		respCode = 400
		respStr = "Unsupported language code: " + lang + ". Choose one of these:"
		cursor.execute("select LangCode2Ltr from TargetLanguages")
		for language in cursor:
			respStr = respStr + " " + language[0]
		return (respStr, respCode)
	else:
		logger.debug("Will use the following language ID: " + str(language[0]) + " " + language[1])
	
	try:
		if len(threads) > 0:
			cursor.execute("insert into PendingJobs(ContentTypeID, ProductID, LanguageID) values (%s, %s, %s)", (contentID, prods[0][0], language[0]))
			jobID = conn.insert_id()
			conn.commit()
			jobQueue.put((jobID, contentID, prods, language, requestContent['data']))
		else:
			respCode = 503
			respStr = "Server unavailable"  
	except:
		logger.debug(traceback.format_exc())
		respCode = 500
		respStr = "Unable to start thread, try after some time"

	conn.close()

	return (respStr, respCode)

def buildQuickAccess(cursor):
	quickAccess = dict()
	cursor.execute("select ID, LangName from TargetLanguages order by LangCode2Ltr asc")
	quickAccess['language'] = cursor.fetchall()
	cursor.execute("select ID, ProductName from Products order by ProductName asc")
	quickAccess['product'] = cursor.fetchall()
	return quickAccess

@app.route('/', methods=['GET'])
@app.route('/index.html', methods=['GET', 'POST'])
def index():
	global mainKey
	form = LoginForm()
	loginOK = None
	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if form.validate_on_submit():
		logger.debug("Login attempted when loading index!")
		key = triple_des(mainKey, pyDes.CBC, mainIV)
		password = form.password.data.encode("utf-8")
		cryptoPass = key.encrypt(password.encode('utf-16le'), padmode=pyDes.PAD_PKCS5).encode('base64').rstrip()
		username = escape(form.username.data.lower()).encode('ascii', 'xmlcharrefreplace')
		logger.debug("Username:" + username)
		xmlResult = urllib2.urlopen(urllib2.Request(url="https://lsweb.autodesk.com/WWLAdminDS/WWLAdminDS.asmx", data=render_template('authentication.xml', username=username, password=cryptoPass), headers={"SOAPAction": "http://tempuri.org/GetUserAuth", "Content-Type": "text/xml; charset=utf-8"})).read()
# 		logger.debug(xmlResult.decode("utf-8"))
		result = re.search('<GetUserAuthResult>.*<ID_USER>(\d+)</ID_USER>.*<FIRSTNAME>([\w \'-]+)</FIRSTNAME>.*<LASTNAME>([\w \'-]+)</LASTNAME>.*</GetUserAuthResult>', xmlResult.decode("utf-8"), re.U)
		if result:
			userID = int(result.group(1))
			userFirstName = result.group(2)
			userLastName = result.group(3)
			conn = connectToDB()
			cursor = conn.cursor()
			cursor.execute("insert into Users(ID, FirstName, LastName) values(%s, %s, %s) on duplicate key update FirstName=%s, LastName=%s", (userID, userFirstName, userLastName, userFirstName, userLastName))
			conn.commit()
			conn.close()
			session['UserID'] = userID
			session['UserFirstName'] = userFirstName
			session['UserLastName'] = userLastName
			loginOK = True
			if form.remember_me.data:
				session['RememberMe'] = form.remember_me.data
				session['UserLogin'] = username
				session['UserPassword'] = cryptoPass
				session.permanent = True
				app.permanent_session_lifetime = timedelta(days=365)
			else:
				session.pop('RememberMe', None)
				session.pop('UserLogin', None)
				session.pop('UserPassword', None)
				session.permanent = False
		else:
			loginOK = False
		
	elif 'UserID' in session:
		logger.debug("UserID encountered when loading index!")
		loginOK = True
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
		
	elif 'RememberMe' in session:
		logger.debug("RememberMe encountered when loading index!")
		result = None
		if 'UserLogin' in session:
			key = triple_des(mainKey, pyDes.CBC, mainIV)
			xmlResult = urllib2.urlopen(urllib2.Request(url="https://lsweb.autodesk.com/WWLAdminDS/WWLAdminDS.asmx", data=render_template('authentication.xml', username=session['UserLogin'], password=session['UserPassword']), headers={"SOAPAction": "http://tempuri.org/GetUserAuth", "Content-Type": "text/xml; charset=utf-8"})).read()
#			logger.debug(xmlResult)
			result = re.search('<GetUserAuthResult>.*<ID_USER>(\d+)</ID_USER>.*<FIRSTNAME>([\w \'-]+)</FIRSTNAME>.*<LASTNAME>([\w \'-]+)</LASTNAME>.*</GetUserAuthResult>', xmlResult.decode("utf-8"), re.U)
		else:
			logger.debug(u"…but UserLogin not found when loading index!".encode("utf-8"))
			session.pop('UserLogin', None)
		if result:
			userID = int(result.group(1))
			userFirstName = result.group(2)
			userLastName = result.group(3)
			conn = connectToDB()
			cursor = conn.cursor()
			cursor.execute("insert into Users(ID, FirstName, LastName) values(%s, %s, %s) on duplicate key update FirstName=%s, LastName=%s", (userID, userFirstName, userLastName, userFirstName, userLastName))
			conn.commit()
			conn.close()
			session['UserID'] = userID
			session['UserFirstName'] = userFirstName
			session['UserLastName'] = userLastName
			loginOK = True
		else:
			if 'UserLogin' in session:
				form = LoginForm(username = session['UserLogin'], remember_me = True)
				if session['UserPassword'] == "":
					loginOK = None
				else:
					loginOK = False
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	recentLangs = recentLanguages(cursor)
	recentProds = recentProducts(cursor)
	lateJobs = latestJobs(cursor)
	quickAccess = buildQuickAccess(cursor)
	conn.close()
	return render_template('index.html',
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			form = form,
			loginOK = loginOK,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)

@app.route('/logout', methods=['GET'])
def logout():
	if 'UserID' in session:
		session.pop('UserID', None)
		session.pop('UserFirstName', None)
		session.pop('UserLastName', None)
	if 'RememberMe' in session:
		session['UserPassword'] = ""
	return ('', 204)

@app.route('/isAuthorised', methods=['GET'])
def isAuthorised():
	if 'UserID' in session:
		return ('YES', 200)
	else:
		return ('NO', 401)

@app.route('/TermList.perl', methods=['GET'])
def TermListPerl():
	language = request.args.get('language', '')
	glossary = request.args.get('glossary', '')
	if not language or not glossary or language == '0' or glossary == '0':
		return ('You have to specify both a language and a glossary!', 400)
	language = re.sub("_", "-", language)
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("select Term, TermTranslation from TermList where LangCode2Ltr = %s and ProductCode in (select ProductCode from ProductGlossaries where GlossaryName = %s) and Approved = b'1' and IgnoreTerm = b'0'", (language, glossary))
	terms = cursor.fetchall()
	conn.close()
	if not terms:
		return ('{}', 200)
	perlHash = '{'
	for term in terms:
		perlHash += '"'+re.sub(r'(["\\])', r'\\\1', term['Term'])+'" => "'+re.sub(r'(["\\])', r'\\\1', term['TermTranslation'])+'",'
	perlHash += '}'
	return (perlHash, 200)

@app.route('/TermList.html', methods=['GET'])
def TermList():
	dbParams = ()
	try:
		dataOffset = int(request.args.get('offset', 0))
	except:
		dataOffset = 0
	try:
		dataPageSize = int(request.args.get('perPage', 10))
	except:
		dataPageSize = 10
	try:
		dataRecords = int(request.args.get('total', 0))
	except:
		dataRecords = 0
	dataOnly = request.args.get('bare', 0)

	jobID = 0
	langID = 0
	prodID = 0
	search = ""
	jobID = request.args.get('jobID', '')
	if not jobID:
		langID = request.args.get('langID', '')
		prodID = request.args.get('prodID', '')
		search = request.args.get('search', '')
	
	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
	
	contentColumnCount = 11
	showProductColumn = False
	showLanguageColumn = False
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	sql = ""
	if jobID:
		contentColumnCount = contentColumnCount + 1
		sql = " from TermList where JobID = %s order by Term asc"
		dbParams += (jobID,)
	else:
		sql = " from TermList"
		if not search or search == '':
			searchsql = ""
		else:
			searchsql = " Term rlike '(^| )%s' " % conn.escape_string(search)
			
		if not langID or langID == '0':
			if not prodID or prodID == '0':
				contentColumnCount = contentColumnCount + 3
				showProductColumn = True
				showLanguageColumn = True
				if searchsql:
					sql = sql + " where" + searchsql
				sql = sql + " order by LangCode3Ltr asc, Term asc, ProductName asc"
			else:
				contentColumnCount = contentColumnCount + 2
				showLanguageColumn = True
				if searchsql:
					searchsql = searchsql + " and"
				sql = sql + " where" + searchsql + " ProductCode = (select ProductCode from Products where ID = %s) order by LangCode3Ltr asc, Term asc" 
				dbParams += (prodID,)
		elif not prodID or prodID == '0':
			contentColumnCount = contentColumnCount + 2#
			showProductColumn = True
			if searchsql:
				searchsql = searchsql + " and"
			sql =  sql + " where" + searchsql + " LangCode3Ltr = (select LangCode3Ltr from TargetLanguages where ID = %s) order by Term asc, ProductName asc" 
			dbParams += (langID,)
		else:
			contentColumnCount = contentColumnCount + 1
			if searchsql:
				searchsql = searchsql + " and"
			sql =  sql + " where" + searchsql + " LangCode3Ltr = (select LangCode3Ltr from TargetLanguages where ID = %s) and ProductCode = (select ProductCode from Products where ID = %s) order by Term asc"
			dbParams += (langID, prodID, )
	if not dataRecords or dataRecords == '0':
# 		logger.debug("Counting total terms using following SQL:\n"+"select count(TermID) as Records"+sql)
		cursor.execute("select count(TermID) as Records"+sql, dbParams)
		recordCount = cursor.fetchone()
		if recordCount:
			dataRecords = recordCount['Records']
		else:
			dataRecords = 0
	terms = None
	if dataRecords > 0:
		if dataOffset >= dataRecords:
			dataOffset = 0
# 		logger.debug("Selecting terms to display using following SQL:\n"+"select *"+sql+" limit %s offset %s" % (dataPageSize, dataOffset))
		cursor.execute("select *"+sql+" limit %s offset %s", dbParams + (dataPageSize, dataOffset))
		terms = cursor.fetchall()
	recentLangs = recentLanguages(cursor)
	recentProds = recentProducts(cursor)
	lateJobs = latestJobs(cursor)
	quickAccess = buildQuickAccess(cursor)
	language = ""
	productName = ""
	if jobID:
		cursor.execute("select LangName, ProductName from JobList where JobID = %s limit 1", (jobID,))
		result = cursor.fetchone()
		if result:
			language = result['LangName']
			productName = result['ProductName']
		cursor.execute("select LanguageID, ProductID from PendingJobs where ID = %s limit 1", (jobID,))
		result = cursor.fetchone()
		if result:
			langID = result['LanguageID']
			prodID = result['ProductID']
	else:
		if langID and langID != '0':
			cursor.execute("select LangName from TargetLanguages where ID = %s limit 1", (langID,))
			result = cursor.fetchone()
			if result:
				language = result['LangName']
		else:
			langID = 0
		if prodID and prodID != '0':
			cursor.execute("select ProductName from Products where ID = %s limit 1", (prodID,))
			result = cursor.fetchone()
			if result:
				productName = result['ProductName']
		else:
			prodID = 0
	if terms:
		cursor.execute("update TargetLanguages set LastUsed=CURRENT_TIMESTAMP where LangCode3Ltr=%s limit 1",  (terms[0]['LangCode3Ltr'],))
		cursor.execute("update Products set LastUsed=CURRENT_TIMESTAMP where ProductCode=%s limit 1", (terms[0]['ProductCode'],))
		conn.commit()
		conn.close()
		productCode = ""
		contentType = ""
		if not search or search == "":
			productCode = terms[0]['ProductCode']
			contentType = terms[0]['ContentType']
		if not dataOnly or dataOnly == '0':
			return render_template('TermList.html',
				contentColumnCount = contentColumnCount,
				perPage = dataPageSize,
				page = (int(dataOffset) / int(dataPageSize) + 1),
				total = dataRecords,
				jobID = jobID,
				langID = langID,
				prodID = prodID,
				searchTerm = search,
				language = language,
				productCode = productCode,
				productName = productName,
				contentType = contentType,
				recentLanguages = recentLangs,
				recentProducts = recentProds,
				latestJobs = lateJobs,
				quickAccess = quickAccess,
				userID = userID,
				userName = userFirstName + " " + userLastName,
				STAGING = isStaging)
		else:
			return render_template('TermListTable.html',
				terms = terms,
				contentColumnCount = contentColumnCount,
				showProductColumn = showProductColumn,
				showLanguageColumn = showLanguageColumn
				)
	elif jobID:
		cursor.execute("select concat('job ', concat_ws(', ', ProductCode, LangCode3Ltr, ContentType)) as JobString from JobList where JobID = %s limit 1", (jobID,))
		jobString = cursor.fetchone()
		if not jobString:
			jobStringTxt = ""
		else:
			jobStringTxt = jobString['JobString']
		conn.close()
		return render_template('TermList.html',
			jobString = jobStringTxt,
			total = 0,
			jobID = jobID,
			language = language,
			productName = productName,
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
	else:
		cursor.execute("select concat_ws(', ', ProductName, LangName) as JobString from Products, TargetLanguages where Products.ID = %s and TargetLanguages.ID = %s limit 1", (prodID, langID))
		jobString = cursor.fetchone()
		if not jobString:
			jobStringTxt = ""
		else:
			jobStringTxt = jobString['JobString']
		conn.close()
		return render_template('TermList.html',
			jobString = jobStringTxt,
			searchTerm = search,
			total = 0,
			language = language,
			productName = productName,
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
					
@app.route('/terminology.tbx', methods=['GET'])
def terminology():
	
	jobID = 0
	langID = 0
	prodID = 0
	jobID = request.args.get('jobID', '')

	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	if jobID:
		cursor.execute("select * from TermList where Approved = b'1' and IgnoreTerm = b'0' and JobID = %s order by Term asc", (jobID,))
	else:
		langID = request.args.get('langID', '')
		prodID = request.args.get('prodID', '')
		if not langID or langID == '0':
			if not prodID or prodID == '0':
				cursor.execute("select * from TermList where Approved = b'1' and IgnoreTerm = b'0' order by LangCode3Ltr asc, Term asc, ProductName asc")
			else:
				cursor.execute("select * from TermList where Approved = b'1' and IgnoreTerm = b'0' and ProductCode = (select ProductCode from Products where ID = %s) order by LangCode3Ltr asc, Term asc", (prodID,))
		elif not prodID or prodID == '0':
			cursor.execute("select * from TermList where Approved = b'1' and IgnoreTerm = b'0' and LangCode3Ltr = (select LangCode3Ltr from TargetLanguages where ID = %s) order by Term asc, ProductName asc", (langID,))
		else:
			cursor.execute("select * from TermList where Approved = b'1' and IgnoreTerm = b'0' and ProductCode = (select ProductCode from Products where ID = %s) and LangCode3Ltr = (select LangCode3Ltr from TargetLanguages where ID = %s) order by Term asc, ProductName asc", (prodID, langID,))
	
	terms = cursor.fetchall()
	glossary = {}
	for term in terms:
		if term['Term'] not in glossary:
			glossary[term['Term']] = []
		glossary[term['Term']].append(term)
	
	recentLangs = recentLanguages(cursor)
	recentProds = recentProducts(cursor)
	lateJobs = latestJobs(cursor)
	quickAccess = buildQuickAccess(cursor)
	if terms:
		response = make_response(render_template('terminology.tbx',
			jobID = jobID,
			langID = langID,
			prodID = prodID,
			termBaseTitle = 'tbd',
			terms = glossary,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging))
		response.headers['Content-Disposition'] = "attachment; filename=glossary.tbx"
		response.headers['Content-Type'] = "text/tbx; charset=utf-8"
		return response
	elif jobID:
		cursor.execute("select concat('job ', concat_ws(', ', ProductCode, LangCode3Ltr, ContentType)) as JobString from JobList where JobID = %s limit 1", (jobID,))
		jobString = cursor.fetchone()
		conn.close()
		return render_template('TermList.html',
			jobString = jobString['JobString'],
			total = 0,
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
	else:
		if not langID or langID == '0':
			if not prodID or prodID == '0':
				cursor.execute("select concat_ws(', ', 'All products', 'All languages')")
			else:
				cursor.execute("select concat_ws(', ', ProductName, 'All languages') as JobString from Products where Products.ID = %s limit 1", (prodID,))
		elif not prodID or prodID == '0':
			cursor.execute("select concat_ws(', ', 'All products', LangName) as JobString from TargetLanguages where TargetLanguages.ID = %s limit 1", (langID,))
		else:
			cursor.execute("select concat_ws(', ', ProductName, LangName) as JobString from Products, TargetLanguages where Products.ID = %s and TargetLanguages.ID = %s limit 1", (prodID, langID,))
		jobString = cursor.fetchone()
		conn.close()
		return render_template('TermList.html',
			jobString = jobString['JobString'],
			total = 0,
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
		
@app.route('/JobList.html', methods=['GET'])
def JobList():
	dbParams = ()
	try:
		dataOffset = int(request.args.get('offset', 0))
	except:
		dataOffset = 0
	try:
		dataPageSize = int(request.args.get('perPage', 10))
	except:
		dataPageSize = 10
	try:
		dataRecords = int(request.args.get('total', 0))
	except:
		dataRecords = 0
	dataOnly = request.args.get('bare', 0)

	langID = request.args.get('langID', '')
	prodID = request.args.get('prodID', '')

	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	sql = ""
	if not langID or langID == '0':
		if not prodID or prodID == '0':
			sql = " from JobList"
		else:
			sql = " from JobList where ProductCode = (select ProductCode from Products where Products.ID = %s limit 1)"
			dbParams += (prodID,)
	elif not prodID or prodID == '0':
		sql = " from JobList where LangCode3Ltr = (select LangCode3Ltr from TargetLanguages where TargetLanguages.ID = %s limit 1)"
		dbParams += (langID,)
	else:
		sql = " from JobList where LangCode3Ltr = (select LangCode3Ltr from TargetLanguages where TargetLanguages.ID = %s limit 1) and ProductCode = (select ProductCode from Products where Products.ID = %s limit 1)"
		dbParams += (langID, prodID,)
	if not dataRecords or dataRecords == '0':
# 		logger.debug("Counting total jobs using following SQL:\n"+"select count(TermID) as Records"+sql)
		cursor.execute("select count(JobID) as Records"+sql, dbParams)
		recordCount = cursor.fetchone()
		if recordCount:
			dataRecords = recordCount['Records']
		else:
			dataRecords = 0
	jobs = None
	if dataRecords > 0:
		if dataOffset >= dataRecords:
			dataOffset = 0
# 		logger.debug("Selecting jobs to display using following SQL:\n"+"select *"+sql+" limit %s offset %s" % (dataPageSize, dataOffset))
		cursor.execute("select *"+sql+" limit %s offset %s", dbParams + (dataPageSize, dataOffset))
		jobs = cursor.fetchall()

	language = None
	if langID and langID != '0':
		cursor.execute("select LangName from TargetLanguages where ID = %s", (langID,))
		language = cursor.fetchone()
		if language:
			language = language['LangName']
	product = None
	if prodID and prodID != '0':
		cursor.execute("select ProductName from Products where ID = %s", (prodID,))
		product = cursor.fetchone()
		if product:
			product = product['ProductName']
	recentLangs = recentLanguages(cursor)
	recentProds = recentProducts(cursor)
	quickAccess = buildQuickAccess(cursor)
	conn.close()
	if not dataOnly or dataOnly == '0':
		return render_template('JobList.html',
			perPage = dataPageSize,
			page = (int(dataOffset) / int(dataPageSize) + 1),
			total = dataRecords,
			langID = langID,
			prodID = prodID,
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			quickAccess = quickAccess,
			language = language,
			product = product,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
	else:
		return render_template('JobListTable.html',
			jobs = jobs)

@app.route('/LanguageList.html', methods=['GET'])
def LanguageList():
	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("select * from LanguageList")
	languages = cursor.fetchall()
	recentProds = recentProducts(cursor)
	lateJobs = latestJobs(cursor)
	quickAccess = buildQuickAccess(cursor)
	conn.close()
	if languages:
		return render_template('LanguageList.html',
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			languages = languages,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
	else:
		return render_template('LanguageList.html',
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)

@app.route('/GenerateReports.html', methods=['GET']) 
def generateReports():
	
	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
	
	prodCode = request.args.get('prodCode', '')
	language = request.args.get('langCode', '')
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	
	lateJobs = latestJobs(cursor)
	quickAccess = buildQuickAccess(cursor)
	
	sql  = "select LangName, VerifyUserID, t1.Modified, t2.LeftAlone, t2.ProductName from" 
	sql += " (select TermList.LangName, TermList.VerifyUserID, ProductName, count(*) as Modified from TermList where Verified = b'1' and IgnoreTerm = b'0'"  
	sql += " and (TermList.TranslateUserID = VerifyUserID or" 
	sql += " TermList.VerifyUserID in (select getUserNameByID(Archive.TranslateUserID) from Archive where TermTranslationID = TermID))"  
	sql += " and HasArchive = 1" 
	
	if prodCode:
		sql += " and ProductCode = %s"
	elif language:
		sql += " and TermList.LangName = %s"
	else:
		sql += " and ProductCode = %s"
		
	sql += " group by TermList.VerifyUserID"  
	sql += " order by TermList.LangCode2Ltr asc, TermList.VerifyUserID asc) as t1"  
	sql += " right join" 
	sql += " (select TermList.LangName, TermList.VerifyUserID, ProductName, count(*) as LeftAlone from TermList where Verified = b'1' and IgnoreTerm = b'0'"  
	sql += " and (TermList.TranslateUserID != VerifyUserID and" 
	sql += " TermList.VerifyUserID not in (select getUserNameByID(Archive.TranslateUserID) from Archive where TermTranslationID = TermID))"  
	
	if prodCode:
		sql += " and ProductCode = %s"
	elif language:
		sql += " and TermList.LangName = %s"
	else:
		sql += " and ProductCode = %s" 
	
	sql += " group by TermList.VerifyUserID"  
	sql += " order by TermList.LangCode2Ltr asc, TermList.VerifyUserID asc) as t2"  
	sql += " using (VerifyUserID, LangName)"
	
	if language:
		sql += " order by  t2.ProductName"
	
	if prodCode:
		cursor.execute(sql,(prodCode, prodCode))
	elif language:
		cursor.execute(sql,(language, language))
	else:
		cursor.execute(sql,(prodCode, prodCode))
	
	reports = cursor.fetchall()
	
	sql = "select * from ProductList order by productname"
	cursor.execute(sql)
	products = cursor.fetchall()
	
	sql = "select * from TargetLanguages order by langname"
	cursor.execute(sql)
	langs = cursor.fetchall()
	
	return render_template('GenerateReports.html',
		reports = reports,
		products = products,
		prodCode = prodCode,
		langs = langs,
		language = language,
		latestJobs = lateJobs,
		quickAccess = quickAccess,
		userID = userID,
		userName = userFirstName + " " + userLastName,
		STAGING = isStaging)

@app.route('/ProductList.html', methods=['GET'])
def ProductList():
	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("select * from ProductList")
	products = cursor.fetchall()
	recentLangs = recentLanguages(cursor)
	lateJobs = latestJobs(cursor)
	quickAccess = buildQuickAccess(cursor)
	conn.close()
	if products:
		return render_template('ProductList.html',
			recentLanguages = recentLangs,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			products = products,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
	else:
		return render_template('ProductList.html',
			recentLanguages = recentLangs,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)

@app.route('/ContentList.html', methods=['GET'])
def ContentList():
	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']
	
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("select * from ContentList")
	contentTypes = cursor.fetchall()
	recentLangs = recentLanguages(cursor)
	recentProds = recentProducts(cursor)
	lateJobs = latestJobs(cursor)
	quickAccess = buildQuickAccess(cursor)
	conn.close()
	if contentTypes:
		return render_template('ContentList.html',
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			contentTypes = contentTypes,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
	else:
		return render_template('ContentList.html',
			recentLanguages = recentLangs,
			recentProducts = recentProds,
			latestJobs = lateJobs,
			quickAccess = quickAccess,
			userID = userID,
			userName = userFirstName + " " + userLastName,
			STAGING = isStaging)
			
@app.route('/archiveForTerm/<termID>', methods=['GET'])
def archiveForTerm(termID):
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("select TermTranslation, DateTranslated, getUserNameByID(Archive.TranslateUserID) as TranslateUserID from Archive where TermTranslationID = %s order by DateTranslated desc", (termID,))
	archive = cursor.fetchall()
	conn.close()
	return render_template('ArchiveList.html',
		archive = archive,
		STAGING = isStaging)

@app.route('/contextForTerm/<termID>', methods=['GET'])
def contextForTerm(termID):
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("select SourceContext, MTofContext, ContentType from TermContexts inner join ContentTypes on ContentTypeID = ContentTypes.ID where TermTranslationID = %s order by SourceContext asc limit 20", (termID,))
	contexts = cursor.fetchall()
	conn.close()
	return render_template('ContextList.html',
		contexts = contexts,
		STAGING = isStaging)

@app.route('/commentsForTerm/<termID>', methods=['GET'])
@app.route('/commentsForTerm/<termID>/<newComment>', methods=['GET'])
def commentsForTerm(termID, newComment='0'):
	userID = 0
	userFirstName = ""
	userLastName = ""
	
	if 'UserID' in session:
		userID = session['UserID']
		userFirstName = session['UserFirstName']
		userLastName = session['UserLastName']

	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("select ID, Comment, getUserNameByID(TermComments.UserID) as UserID, CommentDate, (TermComments.UserID = %s) as ToDelete from TermComments where TermTranslationID = %s order by CommentDate desc", (userID, termID))
	comments = cursor.fetchall()
	conn.close()
	return render_template('CommentsList.html',
		new = newComment == '1',
		termID = termID,
		comments = comments,
		userID = userID,
		userName = userFirstName + " " + userLastName,
		STAGING = isStaging)

@app.route('/addCommentsForTerm', methods=['POST'])
def addCommentsForTerm():
	content = convertContent(request.get_json())
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	cursor.execute("insert into TermComments(TermTranslationID, Comment, UserID) values(%s, %s, %s)", (content['TermTranslationID'], content['Comment'], content['UserID']))
	cursor.execute("select last_insert_id() as ID")
	commentID = cursor.fetchone()
	cursor.execute("update TermTranslations set DateUpdated=CURRENT_TIMESTAMP where ID=%s limit 1", (content['TermTranslationID'],))
	conn.commit()
	cursor.execute("select CommentDate, getUserNameByID(%s) as UserID from TermComments where ID = %s limit 1", (content['UserID'], commentID['ID']))
	result = cursor.fetchone()
	content['CommentDate'] = result['CommentDate']
	content['UserID'] = result['UserID']
	content['ID'] = commentID['ID']
	conn.close()
	return render_template('CommentRow.html',
		comment = content)
		
@app.route('/deleteComment', methods=['POST'])
def deleteComment():
	content = convertContent(request.get_json())
	conn = connectToDB()
	cursor = conn.cursor()
	cursor.execute("delete from TermComments where ID = %s", (content['ID'],))
	cursor.execute("update TermTranslations set DateUpdated=CURRENT_TIMESTAMP where ID=%s limit 1", (content['TermID'],))
	conn.commit()
	conn.close()
	return ("", 204)

def convertContent(content):
	result = {}
	for datum in content:
		result[datum['name']] = datum['value']
	return result
	
@app.route('/translateTerm', methods=['POST'])
def translateTerm():
	content = convertContent(request.get_json())
	conn = connectToDB()
	cursor = conn.cursor(pymysql.cursors.DictCursor)
	if content['IgnoreTerm']:
		content['IgnoreTerm'] = '1'
	else:
		content['IgnoreTerm'] = '0'
	if content['Verified']:
		content['Verified'] = '1'
	else:
		content['Verified'] = '0'
	if content['Approved']:
		content['Approved'] = '1'
	else:
		content['Approved'] = '0'
	cursor.execute("update TermTranslations set IgnoreTerm=b%s, TermTranslation=%s, TranslateUserID=%s, Verified=b%s, Approved=b%s where TermTranslations.ID=%s limit 1", (content['IgnoreTerm'], content['TermTranslation'], content['UserID'], content['Verified'], content['Approved'], content['TermID']))
	conn.commit()
	cursor.execute("select * from TermList where TermID=%s limit 1", (content['TermID'],))
	termTranslation = content['TermTranslation']
	content, = cursor.fetchall()
	conn.close()
	# push approved term translation to Solr/NeXLT
	if (content['Approved'] == '\x01'): # \x01 = binary TRUE from DB; \x00 = binary FALSE
		pushTermTranslationToSolr("enu", content['Term'], content['LangCode3Ltr'], termTranslation, content['ProductCode'], content['ProductName'])
	content['DateRequested'] = str(content['DateRequested'])
	content['DateUpdated'] = str(content['DateUpdated'])
	content['DateTranslated'] = str(content['DateTranslated'])
	content['IgnoreTerm'] = str(content['IgnoreTerm'])
	content['Verified'] = str(content['Verified'])
	content['Approved'] = str(content['Approved'])
	content['HasArchive'] = str(content['HasArchive'])
	content['HasComments'] = str(content['HasComments'])
	return json.dumps(content)
	
def cleanup(*args):
	global threads
	global exitFlag
	if len(threads) > 0:
		exitFlag = True
		for t in threads:
			t.join()
	sys.exit(0)

def pushTermTranslationToSolr(sourceLanguage, termSourceLanguage, targetLanguage, termTargetLanguage, productCode, productName):
	'''
	Pushes a term translation to Solr and thus makes it available in NeXLT.
	
	If this application is run in STAGING mode, the term translation will be pushed to Solr staging.
	
	@param sourceLanguage the 3-letter code of the source language; normally "enu"
	@param termSourceLanguage the term in the source language, e.g., "data collection settings"
	@param targetLanguage the 3-letter code of the target language, e.g., "deu"
	@param termTargetLanguage the term in the target language, i.e., the translation of @paramtermSource Language. Example: "Einstellungen zur Datenerfassung"
	@param productCode the code of the product the term stems from, e.g., "CIV3D"
	@param productName the full name of the product the term stems from, e.g., "AutoCAD Civil 3D"
	'''
	# settings
	solr_host_prd = "http://aws.prd.solr:8983" #production
	solr_host_stg = "http://aws.stg.solr:8983" #staging
	solr_request_path = "/search/update/json"
	
	# Compose the unique identifier for a (source) term in Solr.
	termID = md5.new(u"".join([termSourceLanguage, productCode]).encode("utf-8")).hexdigest() + "Terminology"
	
	# compose REST call
	# First remove and then add the full product name to avoid duplicates in this multivalue Solr field.
	json_request = """{
	   "add":{
	      "doc":{
	         "resource":{
	            "set":"Terminology"
	         },
	         "product":{
	            "set": %s
	         },
	         "productname":{
	            "remove": %s
	         },
	         "id": %s,
	         %s :{
	            "set": %s
	         },
	         %s :{
	            "set": %s
	         },
	         "srclc":{
	            "set": %s
	         }
	      }
	   },
	   "add":{
	      "doc":{
	         "id": %s,
	         "productname":{
	            "add": %s
	         }
	      }
	   },
	   "commit": {}
	}""" % (json.dumps(productCode), 
		json.dumps(productName),
		json.dumps(termID), 
		json.dumps(sourceLanguage),
		json.dumps(termSourceLanguage),
		json.dumps(targetLanguage),
		json.dumps(termTargetLanguage),
		json.dumps(termSourceLanguage.lower()),
		json.dumps(termID),
		json.dumps(productName))
	json_headers = {'Content-type': 'application/json'}
	# fire REST call
	request_url = solr_host_stg + solr_request_path if (isStaging) else solr_host_prd + solr_request_path
	try:
		response = requests.post(request_url, data=json_request, headers=json_headers)
# 		logger.info("Pushed approved term translation for '%s' (%s) to Solr." % (termSourceLanguage, targetLanguage))
	except:
		error = sys.exc_info()
		logger.warning("Could not push approved term translation for '%s' (%s) to Solr/NeXLT. Reason: %s" % (termSourceLanguage, targetLanguage, error))
		logger.debug("Request: " + json_request)
		try:
			logger.debug("Response: " + response)
		except:
			pass
	

jobQueue = Queue.Queue()
threads = []

thread = termHarvestThread(len(threads) + 1)
thread.start()
threads.append(thread)
