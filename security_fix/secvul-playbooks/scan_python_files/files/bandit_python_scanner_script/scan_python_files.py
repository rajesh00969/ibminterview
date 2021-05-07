from subprocess import Popen, PIPE
from sys import exit as sysexit
from collections import defaultdict
import argparse
from random import randint
import logging
import shlex


# Basic Logger to log the information during run time and for debugging
logging.basicConfig(filename='scan_python_files.log', level=logging.INFO, filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s - %(levelname)s %(message)s',
                    datefmt="%Y-%m-%d %H:%M:%S")

# Arg Parser to get the folder where reports will be stored.
parseme = argparse.ArgumentParser()
parseme.add_argument("--outputfolder", help="Bandit reports will be stored in this folder.")
parseme.add_argument("--sudopassword", help="sudopassword required to run find command.")


arguments = parseme.parse_args()
if not (arguments.outputfolder and arguments.sudopassword):
    print("Kindly mention the output folder. for more help use -h / --help")
    print('Example usage - python name.py --outputfolder \"/tmp\" --sudopassword "pass" ')
    exit(0)

outputfolder = arguments.outputfolder
sudopassword = '{0}{1}'.format(arguments.sudopassword, '\n')

exclude_path_list = ['/.ansible/']


# !!!***** CAUTION *****!!!
# Static Linux Contents - DO NOT MODIFY.
# The variables declared below are about to execute in shell
# directly with highest privilege. <0.0>

lx_find_cmd = r'sudo find / \( -path "/opt/*" -o -path "/home/*" -o -path "/mnt/*"  \) -type f -iname *.py'
lx_checksum = r'sudo md5sum {file_name}'
lx_bandit = ''' sudo bandit {py_filename} --format html --output {output_directory}'''


def validate_checksum(filename):
    """
    This method will calculete the checksum value
    of the files passed to it with the help of
    linux buildin md5sum tool.
    :param filename: Input file - String type.
    :return: md5 value of the file - String type.
    """
    try:
        lx_md5sum_output = Popen(shlex.split(lx_checksum.format(file_name=filename)), stderr=PIPE, stdout=PIPE)
        md5_stdout, md5_stderr = lx_md5sum_output.communicate(sudopassword)
        if md5_stderr:
            logging.error("md5sum command ended with bad exit code ")
            logging.error("Error Output, ", md5_stderr)
        if md5_stdout:
            return md5_stdout.split(' ')[0]
        else:
            logging.info("Empty Response")
            return None
    except (ValueError, OSError) as err:
        logging.error("Check the arguments passed to Popen method and also validate the command passed to it.")
        logging.exception(err)


def get_py_files_location():
    """
    This method will find the non-system python files and stores
    the python files with its checksum value and absolute path in a dict.
    :return: python files with it's checksum value - dict data type.
    """
    py_files_with_absolute_path = defaultdict(list)
    py_files = []
    try:
        get_py_path_cmd = Popen(shlex.split(lx_find_cmd), stdout=PIPE, stderr=PIPE, stdin=PIPE)
        find_cmd_stdout, find_cmd_stderr = get_py_path_cmd.communicate(sudopassword)
        logging.error(find_cmd_stderr)
        logging.info(find_cmd_stdout)
        py_files_unrefined = list(filter(None, find_cmd_stdout.strip().split('\n')))
        if find_cmd_stderr:
            logging.exception("Error occurred will finding py files cmd= ", lx_find_cmd)
        if py_files_unrefined:
            for items in py_files_unrefined:
                for words in exclude_path_list:
                    if words not in items:
                        py_files.append(items)
            if py_files:
                to_blackhole = list(map(lambda x: py_files_with_absolute_path[validate_checksum(x)].append(x),
                                        py_files))
                del to_blackhole
            if py_files_with_absolute_path:
                return py_files_with_absolute_path
        else:
            return None
    except (ValueError, OSError) as err:
        logging.error("Check the arguments passed to Popen method and also validate the command passed to it.")
        logging.exception(err)
        sysexit(1)


def scan_py_files(file_name):
    """
    This method will scan the python files using bandit package.
    :param file_name: List of python files to be scanned
    :return: Filename and stdout
    """
    try:
        output_filename = '{0}/{1}_pyfile_report.html'.format(
            outputfolder.rstrip('/'), '_'.join(filter(None, file_name.split('/')[:])))
        scan_py_output = Popen(shlex.split(lx_bandit.format(py_filename=file_name, output_directory=output_filename)),
                               stdout=PIPE, stderr=PIPE, stdin=PIPE)
        scan_py_stdout, scan_py_stderr = scan_py_output.communicate(sudopassword)
        print('Successfully scanned {0} file using bandit tool'.format(file_name))
        return file_name, scan_py_stdout, scan_py_stderr
    except (ValueError, OSError) as err:
        logging.error("Check the arguments passed to Popen method and also validate the command passed to it.")
        logging.exception(err)
        sysexit(1)


if __name__ == '__main__':
    list_of_py_files = get_py_files_location()
    for key, value in list_of_py_files.items():
        findbugscan_out = scan_py_files(file_name=(value[randint(0, len(value)-1)]))
        logging.info(findbugscan_out)
