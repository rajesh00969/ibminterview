#!/usr/bin/python

import yaml
import logging
from sys import stdout
from subprocess import Popen, PIPE, CalledProcessError
from datetime import datetime
from shutil import rmtree
from os import remove, path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

logging.basicConfig(stream=stdout, level=logging.INFO, format='%(asctime)s - %(name)s - '
                                                              '%(levelname)s - %(funcName)s - %(message)s')

_RET_PASS = 0
_FILE_TAG = datetime.now().strftime('%d_%m_%Y_%H_%M')
_FILE_NAME = '{rootpath}/{db}_{time}'
_FILE_NAME_ZIP = '{db}_{time}.zip'
_MONGO_BKP_CMD = '{path} -u {usr} -p {pas} --gzip  --authenticationDatabase {authdb} --db {bkpdb} -o {outfile} '
_MONGO_BKP_NOAUTH_CMD = '{path} --gzip --db {bkpdb} -o {outfile} '
_ZIP_CMD = 'zip -rj {name} {dirname}/{db}/'
_S3_CMD = 'aws s3 cp {bkp_dir}/{zip_name} s3://{bucket_name}/{folder_name}/ --quiet'
_SMTP_ADDRESS = ''
_SMTP_MSG = '''Backup failed for DB - 
{db_list}'''
_SUBJECT = '{env} Env DB backup Status'

def run_cmd(cmd):
    """
    This func will inject the raw linux commands in the shell.
    :param cmd: cmd to be executed.
    :return: output of the command.
    """
    try:
        cmd_output_raw = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
        cmd_output = cmd_output_raw.communicate()
        logging.info('CMD return code: {0}'.format(str(cmd_output_raw.returncode)))
        logging.info(str(cmd_output))
        return cmd_output_raw.returncode
    except (CalledProcessError, OSError) as err:
        logging.exception(err)
        logging.critical('Failed when running this command -- {0}'.format(cmd))
        return False


def load_config(conf_file='config.yaml'):
    """
    This Func will load the config file.
    :param conf_file: path to the config file.
    :return: Loaded data (Dict)
    """
    try:
        with open(conf_file, 'rb') as file:
            conf_payload = yaml.safe_load(file)
            return conf_payload
    except yaml.YAMLError as err:
        logging.exception(err)
        logging.critical("Failed when loading the {0} file".format(conf_file))


def cleanup(payload, fstype):
    """
    This func will clean up the backup files after pushing.
    :param payload: files list
    :param fstype: file type. Directory/file.
    :return: status.
    """
    if fstype == 'File':
        try:
            logging.info("Removing file {0}".format(payload))
            if path.exists(payload):
                remove(payload)
            else:
                logging.warning("File not found -- {0} ".format(payload))
            return True
        except Exception as err:
            logging.exception(err)
            logging.critical("Unable to remove file -- {0}".format(payload))
            return False
    if fstype == "Directory":
        try:
            logging.info("Removing directory {0}".format(payload))
            if path.exists(payload):
                rmtree(payload)
            else:
                logging.warning("File not found -- {0} ".format(payload))
            return True
        except Exception as err:
            logging.exception(err)
            logging.critical("Unable to remove dir -- {0}".format(payload))
            return False


def push_backup_s3(payload, bucket_name, backup_folder):
    """
    This func will push the backup to s3.
    :param payload: backup config
    :param bucket_name: backup config
    :param backup_folder: backup root folder
    :return:
    """
    s3_push_pass = []
    s3_push_fail = []
    for archives in payload:
        s3_cmd = _S3_CMD.format(bkp_dir=backup_folder, zip_name=payload.get(archives, {}).get('zip_name'),
                                bucket_name=bucket_name, folder_name=archives)
        s3_status = run_cmd(s3_cmd)
        if s3_status == _RET_PASS:
            s3_push_pass.append(archives)
            cleanup('{0}/{1}'.format(backup_folder, payload.get(archives, {}).get('zip_name')), "File")
            return True
        else:
            s3_push_fail.append(archives)
            cleanup('{0}/{1}'.format(backup_folder, payload.get(archives, {}).get('zip_name')), "File")
            return False


def archive_dbfiles(file_list, backup_folder, payload):
    """
    This Func will archive the backup files.
    :param file_list: list of archives
    :param backup_folder: folder to store the backup.
    :param payload: yaml config.
    :return: status
    """
    archive_metadata = {}
    archive_success = None
    archive_failure = None
    for zip_name in file_list:
        try:
            zip_cmd = _ZIP_CMD.format(name='{0}/{1}'.format(backup_folder, zip_name),
                                      dirname=file_list.get(zip_name, {}).get('dirname'),
                                      db=file_list.get(zip_name, {}).get('dbname'))
            archive_status = run_cmd(zip_cmd)
            if archive_status == _RET_PASS:
                archive_metadata[file_list.get(zip_name, {}).get(
                    'dbname')] = {'zip_name': zip_name, 'rootpath': file_list.get(zip_name, {}).get('rootpath')}
                cleanup(file_list.get(zip_name, {}).get('dirname'), "Directory")
                archive_cp_sts = push_backup_s3(archive_metadata, payload.get('bucket_name'),
                                                payload.get('backup_folder'))
                if archive_cp_sts:
                    archive_success = file_list.get(zip_name, {}).get('dbname')
                else:
                    archive_failure = file_list.get(zip_name, {}).get('dbname')
                archive_metadata = {}
            else:
                archive_failure = file_list.get(zip_name, {}).get('dbname')
                cleanup(file_list.get(zip_name, {}).get('dirname'), "Directory")
        except Exception as err:
            logging.exception(err)
            cleanup(file_list.get(zip_name, {}).get('dirname'), "Directory")
            logging.critical("Failed when archiving backup -- {0}".format(zip_name))
    logging.info('Archive success list {0}'.format(archive_success))
    logging.info('Archive failure list {0}'.format(archive_failure))
    return archive_success, archive_failure


def initiate_backup(payload):
    """
    This func will initiate the mongo db backup.
    :param payload: backup config
    :return: file list
    """
    backup_file_passed = []
    backup_file_list = {}
    backup_file_list_failed = []
    backup_status = {}
    try:
        for dbs in payload.get('backupdb', None):
            logging.info('Taking backup of {0} DB'.format(dbs))
            db_out_file = _FILE_NAME.format(rootpath=payload['backup_folder'], db=dbs, time=_FILE_TAG)
            db_out_file_zip = _FILE_NAME_ZIP.format(db=dbs, time=_FILE_TAG)
            if payload['authentication']:
                cmd = _MONGO_BKP_CMD.format(
                    path=payload['mongodump_path'], usr=payload['username'],
                    pas=payload['password'], authdb=payload['authdb'], bkpdb=dbs, outfile=db_out_file)
                bkp_out = run_cmd(cmd)
            else:
                cmd = _MONGO_BKP_NOAUTH_CMD.format(
                    path=payload['mongodump_path'],  bkpdb=dbs, outfile=db_out_file)
                bkp_out = run_cmd(cmd)
            if bkp_out == _RET_PASS:
                backup_status[dbs] = 'Pass'
                backup_file_list[db_out_file_zip] = {'rootpath': payload['backup_folder'], 'dbname': dbs,
                                                     'dirname': db_out_file}
                archive_success, archive_failure = archive_dbfiles(backup_file_list,
                                                                             payload.get('backup_folder'), payload)
                if archive_success:
                    backup_file_passed.append(dbs)
                    backup_file_list = {}
                else:
                    backup_status[dbs] = 'Fail'
                    backup_file_list_failed.append(dbs)
                    backup_file_list = {}
            else:
                backup_status[dbs] = 'Fail'
                backup_file_list_failed.append(dbs)
                backup_file_list = {}
                cleanup(db_out_file, 'Directory')
        return backup_file_passed, backup_file_list_failed
    except Exception as err:
        logging.exception(err)
        return False, False


def trigger_email(payload, smtp_address, toaddr, fromaddr, user, pwd, subject):
    """
    This func uses smtp to send the mail.
    :param payload: mail body
    :param toaddr: recipient address (single.)
    :return:
    """
    try:
        msg = MIMEMultipart()
        msg['From'] = fromaddr
        msg['To'] = toaddr
        msg['Subject'] = subject
        msg.attach(MIMEText(payload, 'html'))
        server = smtplib.SMTP(smtp_address, 587)
        server.ehlo()
        server.starttls()
        server.login(user, pwd)
        text = msg.as_string()
        server.sendmail(fromaddr, toaddr, text)
        server.quit()
        return True
    except smtplib.SMTPException as err:
        logging.exception(err)
        return False


if __name__ == '__main__':
    backup_config = load_config()
    backup_files_passed, backup_files_failed = initiate_backup(backup_config.get('mongo_backup_config', None))
    logging.info('Backup completed for -- {0}'.format(backup_files_passed))
    logging.info('Backup failed for -- {0}'.format(backup_files_failed))
    if backup_files_failed:
        config_dict = backup_config.get('mongo_backup_config', None)
        trigger_email(_SMTP_MSG.format(db_list=backup_files_failed), config_dict['smtp_address'],config_dict['toaddr'],
                      config_dict['fromaddr'], config_dict['smtp_user'], config_dict['smtp_pass'],
                      _SUBJECT.format(env=config_dict['environment']))