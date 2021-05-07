from subprocess import Popen, PIPE
from sys import exit as sysexit
from collections import defaultdict
import argparse
from glob import glob
from random import randint
import logging
import shlex

# Basic Logger to log the information during run time and for debugging
logging.basicConfig(filename='scan_java_artifacts.log', level=logging.INFO,
                    filemode='a', format='%(asctime)s,%(msecs)d %(name)s - %(levelname)s %(message)s',
                    datefmt="%Y-%m-%d %H:%M:%S")

# Arg Parser to get the folder where reports will be stored
parseme = argparse.ArgumentParser()
parseme.add_argument("--outputfolder", help="FindBug reports will be stored in this folder.")
parseme.add_argument("--sudopassword", help="sudopassword required to run find and findbugs commands")
parseme.add_argument("--libraryfolder", help="Please mention the FindBug Library Folder")

arguments = parseme.parse_args()
if not (arguments.outputfolder and arguments.sudopassword and arguments.libraryfolder):
    print("Kindly mention the output folder. for more help use -h / --help")
    print('Example usage - python name.py --outputfolder \"/tmp\" --sudopassword "pass" --libraryfolder /tmp/findbugs')
    exit(0)

outputfolder = arguments.outputfolder
sudopassword = '{0}{1}'.format(arguments.sudopassword, '\n')
library_folder = arguments.libraryfolder


# !!!***** CAUTION *****!!!s
# Static Linux Contents - DO NOT MODIFY.
# The variables declared below are about to execute in shell
# directly with highest privilege. <0.0>

lx_find_unformatted = r'sudo find {path} -type f -iname "{file_name}"'
lx_jar_ps = r'ps -axo cmd | grep ".jar" | grep -vi "\-Dcatalina\|logging.properties\|--color\|grep\|python"'
lx_tomcat_ps = r'ps -axo cmd | grep  "\-Dcatalina.base" | grep -vi "\-\-color\=auto\|python"'
lx_checksum = r'sudo md5sum {file_name}'
lx_findBugs = ''' sudo java -cp "{library_folder}" edu.umd.cs.findbugs.LaunchAppropriateUI \
 -quiet -pluginList plugins/findsecbugs-plugin-1.8.0.jar -output {output_filename} -html {input_jar} '''
search_folders = ['/home/', '/mnt/', '/opt/']


def find_jar_process():
    """
    This Method will find the jar process
    running in host for all users.
    With help of process command in linux, the jar process are filtered.
    :return: Returns the raw list of cmd's obtained from linux ps cmd (List datatype)
    """
    try:
        get_jar_process_cmd = Popen(lx_jar_ps, stdout=PIPE, stderr=PIPE, shell=True)
        stdout, stderr = get_jar_process_cmd.communicate()
        if stderr:
            logging.error("Error while executing the command")
            logging.error(stderr)
            sysexit(1)
        if stdout:
            ps_stdout = []
            for temp in map(lambda y: y.split(' '), filter(None, map(lambda x: x, stdout.split('\n')))):
                map(lambda z: ps_stdout.append(z), temp)
            return ps_stdout
        else:
            logging.info("No Jar are running, Checking for War files")
            return None
    except (ValueError, OSError) as err:
        logging.error("Check the arguments passed to Popen method and also validate the command passed to it.")
        logging.exception(err)
        sysexit(1)


def filter_dotjar_files():
    """
    This method will call the find_jar_process method to
    obtain the process tree list from the host.
    And will provide a list with selected jar files.
    that needs to be scanned.
    :return:
    """
    list_of_java_proc = find_jar_process()
    if not list_of_java_proc:
        return None
    absolute_path_breaked_list = []
    matched_jar_files = []
    for items in list_of_java_proc:
        if r'/.m2/' not in items:
            list(map(lambda x: absolute_path_breaked_list.append(x), items.split('/')))
    for words in absolute_path_breaked_list:
        if words.endswith('.jar'):
            matched_jar_files.append(words)
    if matched_jar_files:
        if get_jar_files_location(matched_jar_files):
            return get_jar_files_location(matched_jar_files)
        else:
            return None
    else:
        exit(0)


def get_jar_files_location(jar_list):
    """
    This method will find the non-system jar files and stores
    the jar files with its checksum value and absolute path in a dict.
    :param jar_list: List of jar found in process list - List Data type.
    :return: jar files with it's checksum value - dict data type.
    """
    jar_files_with_absolute_path = defaultdict(list)
    try:
        for jars in jar_list:
            for directory in search_folders:
                lx_find_formatted = lx_find_unformatted.format(path=directory, file_name=jars)
                get_jar_path_cmd = Popen(shlex.split(lx_find_formatted), stdout=PIPE, stderr=PIPE, stdin=PIPE)
                jar_cmd_stdout, jar_cmd_stderr = get_jar_path_cmd.communicate(sudopassword)
                jar_files = list(filter(None, jar_cmd_stdout.split('\n')))
                if jar_cmd_stderr:
                    logging.error("Error occurred will finding jar files cmd= ", lx_find_formatted)
                if jar_files:
                    to_blackhole = list(map(lambda x: jar_files_with_absolute_path[validate_checksum(x)].append(x),
                                            jar_files))
                    del to_blackhole
        if jar_files_with_absolute_path:
            return jar_files_with_absolute_path
        else:
            return None
    except (ValueError, OSError) as err:
        logging.error("Check the arguments passed to Popen method and also validate the command passed to it.")
        logging.exception(err)
        sysexit(1)


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
    except (ValueError, OSError) as err:
        logging.error("Check the arguments passed to Popen method and also validate the command passed to it.")
        logging.exception(err)


def scan_java_artifacts(file_name):
    """
    This method will scan the java artifacts files using findbug 3rd party tool.
    And stores the output in specified folder.
    :param file_name: Jar file absolute path.
    :return: command output and jar file name
    """
    output_report_name = '{0}/{1}_report.html'.format(outputfolder.rstrip('/'),
                                                      '_'.join(filter(None, file_name.split('/')[:])))
    try:
        lx_findbugs_out = Popen(lx_findBugs.format(output_filename=output_report_name, input_jar=file_name,
                                                   library_folder=library_folder),
                                stdout=PIPE, stderr=PIPE, shell=True)
        findbugs_stdout, findbugs_stderr = lx_findbugs_out.communicate(sudopassword)
        if findbugs_stderr:
            logging.error("findbug task ended with bad exit code")
            logging.error(findbugs_stderr)
            return findbugs_stderr
        else:
            print ("Findbugs static code analysis for {0} is completed".format(file_name))
            return file_name, findbugs_stdout
    except (ValueError, OSError) as err:
        logging.error("Findbugs static code analysis failed for {0} file")
        logging.exception(err)
        return file_name, err


def find_war_files():
    """
    This method will find the tomcat process to fetch the tomcat home directory.
    And find the war files to scan it using findbugs.
    :return: command output and war file name - List data type.
    """
    war_files_with_absolute_path = defaultdict(list)
    try:
        lx_tomcat_ps_output = Popen(lx_tomcat_ps, stderr=PIPE, stdout=PIPE, shell=True)
        tomcat_stdout, tomcat_stderr = lx_tomcat_ps_output.communicate()
        if tomcat_stderr:
            logging.error("Error occurred while fetching tomcat process")
            logging.error("Error Output - ", tomcat_stderr)
        if tomcat_stdout:
            tomcat_home_dir = [i.split('=')[1]+"/webapps/*.war" for i in tomcat_stdout.split(' ')
                               if i.startswith('-Dcatalina.base')][0]
            dot_war_files = glob(tomcat_home_dir)
            to_blackhole = list(map(lambda x: war_files_with_absolute_path[validate_checksum(x)].append(x),
                                    dot_war_files))
            del to_blackhole
            return war_files_with_absolute_path
    except (ValueError, OSError) as err:
        logging.error("Findbugs static code analysis failed for {0} file")
        logging.exception(err)
        return None


if __name__ == '__main__':
    java_artifacts = filter_dotjar_files()
    war_files = find_war_files()
    if java_artifacts and war_files:
        for keys, values in war_files.items():
            if java_artifacts.get(keys):
                blackhole = list(map(lambda x: java_artifacts[keys].append(x) if x not in java_artifacts[keys] else None
                                     , java_artifacts[keys]))
            else:
                java_artifacts[keys] = war_files[keys]
    elif war_files:
        java_artifacts = war_files
    else:
        logging.info("No Java process is running, Hence stopping the script !!")
        sysexit(0)
    for key, value in java_artifacts.items():
        print(scan_java_artifacts(value[randint(0, len(value)-1)]))
