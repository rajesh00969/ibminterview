#!/usr/bin/python

# =====================================================================================================================
# title          :OpenStack_Create_Image.py
# description    :This script will initiate image backup for OpenStack critical vm's
# usage          :python OpenStack_Create_Image.py --Profile profile_name --Username 'username' --Password 'password'
# python_version :2.7
# =====================================================================================================================

# Imports
import argparse
from time import sleep
from datetime import datetime
import calendar
from collections import defaultdict
import logging
from sys import stdout
from openstack import connection, exceptions
from profiles import regions_name_hash, profile_maker


logging.basicConfig(stream=stdout, level=logging.INFO,
                    format='%(asctime)s,%(msecs)d %(name)s - %(levelname)s %(message)s')

# Empty global variable for OpenStack connection.
conn = None

date_format = '%Y%m%d'
hour_now = int(datetime.now().strftime('%H'))
date_of_month = int(datetime.now().strftime('%d'))


def parse_args():
    """
    Just a normal method to get the required data to initiate the connection with openstack.
    :return: args: arguments passed to the script.
    """
    parser = argparse.ArgumentParser(description="OpenStack Image backup Kick Starter :) ")
    parser.add_argument('--Password',  help="Enter the password to authenticate")
    parser.add_argument('--Username',  help="Enter the Username to authenticate")
    args = parser.parse_args()
    if args.Password and args.Username:
        return args
    else:
        print 'usage python OpenStack_Create_Image.py --Username user --Password pass'
        exit(1)


def get_sundays():
    sunday = []
    c = calendar.Calendar()
    monthcal = c.monthdatescalendar(int(datetime.today().strftime('%Y')), int(datetime.today().strftime('%m')))
    for week in monthcal:
        for days in week:
            if days.strftime('%B') == datetime.today().strftime('%B'):
                if days.strftime('%A') == 'Sunday':
                    sunday.append(int(days.strftime('%d')))
    sorted(sunday)
    return sunday


def fetch_required_vm():
    """
    This function will form a nested dict that has the data about server_id and its's metadata and volume id's that
    needs to be snapped.
    image_these_vm: {'server_id1: {'server_name': 'instance1' ,'metadata': {'Take_Image': 'Yes'}},
    'server_id2: {'server_name': 'instance1' , 'metadata': {'Take_Image': 'Yes'}}}
    :return: snapshot_these_vm: This will provide a nested dict that contains the structure as mentioned above.
    """
    image_these_vm = {}
    try:
        for servers in conn.compute.servers(status='ACTIVE'):
            if servers.metadata.get('Backup_VM', None) in ['Yes', 'yes']:
                try:
                    if servers.metadata.get('Frequency', None) in ['Daily', 'daily']:
                        if int(servers.metadata.get('Backup_Time', None)) == hour_now:
                            image_these_vm[servers.id] = {}
                            image_these_vm[servers.id]['metadata'] = servers.metadata
                            image_these_vm[servers.id]['server_name'] = servers.name
                            image_these_vm[servers.id]['backup_type'] = []
                            if servers.metadata.get('Image_Snapshot_Backup', None) in ['Yes', 'yes']:
                                image_these_vm[servers.id]['backup_type'].append('Image_Snapshot')
                            if servers.metadata.get('Volume_Snapshot_Backup', None) in ['Yes', 'yes']:
                                image_these_vm[servers.id]['backup_type'].append('Volume_Snapshot')
                                image_these_vm[servers.id]['attached_volumes'] = servers.metadata['Volumes']
                    elif servers.metadata.get('Frequency', None) in ['Monthly', 'monthly']:
                        if date_of_month in [get_sundays()[0]]:
                            if int(servers.metadata.get('Backup_Time', None)) == hour_now:
                                image_these_vm[servers.id] = {}
                                image_these_vm[servers.id]['metadata'] = servers.metadata
                                image_these_vm[servers.id]['server_name'] = servers.name
                                image_these_vm[servers.id]['backup_type'] = []
                                if servers.metadata.get('Image_Snapshot_Backup', None) in ['Yes', 'yes']:
                                    image_these_vm[servers.id]['backup_type'].append('Image_Snapshot')
                                if servers.metadata.get('Volume_Snapshot_Backup', None) in ['Yes', 'yes']:
                                    image_these_vm[servers.id]['backup_type'].append('Volume_Snapshot')
                                    image_these_vm[servers.id]['attached_volumes'] = servers.metadata['Volumes']
                    elif servers.metadata.get('Frequency', None) in ['Monthly_Twice', 'monthly_twice']:
                        if date_of_month in [get_sundays()[0], get_sundays()[-1]]:
                            if int(servers.metadata.get('Backup_Time', None)) == hour_now:
                                image_these_vm[servers.id] = {}
                                image_these_vm[servers.id]['metadata'] = servers.metadata
                                image_these_vm[servers.id]['server_name'] = servers.name
                                image_these_vm[servers.id]['backup_type'] = []
                                if servers.metadata.get('Image_Snapshot_Backup', None) in ['Yes', 'yes']:
                                    image_these_vm[servers.id]['backup_type'].append('Image_Snapshot')
                                if servers.metadata.get('Volume_Snapshot_Backup', None) in ['Yes', 'yes']:
                                    image_these_vm[servers.id]['backup_type'].append('Volume_Snapshot')
                                    image_these_vm[servers.id]['attached_volumes'] = servers.metadata['Volumes']
                    else:
                        logging.info("Skipping image {0}")
                except ValueError:
                    logging.error("Unable to determine backup time.")
                except KeyError:
                    if image_these_vm.get(servers.id, None):
                        del image_these_vm[servers.id]
                    logging.critical("Unable to fetch required values from payload -- ", servers)
            else:
                continue
        logging.info(image_these_vm)
        print image_these_vm
        return image_these_vm
    except (exceptions.HttpException, exceptions.InvalidRequest, exceptions.EndpointNotFound) as e:
        logging.exception(e)
        logging.critical("Unable to fetch server details from openstack")
        exit(1)
    except Exception as e:
        logging.exception(e)
        exit(1)


def get_volume_type(volumes_raw):
    """
    This func will check the volume is bootable or not
    :param volumes_raw: List of volumes(id)
    :return: list of volume id eligible for snapshot
    """
    backup_volumes = []
    volumes = volumes_raw.split(',')
    for volume_id in volumes:
        try:
            if volume_id:
                volume_data = conn.block_storage.get_volume(volume_id)
                if not volume_data.is_bootable:
                    backup_volumes.append(volume_id)
                else:
                    logging.warning("Volume id -- {0} cannot be snapshot -ed, As it is a root volume".format(
                        volume_id))
        except KeyError:
            logging.critical("Unable to fetch volume data Volume id -- ", volume_id)
        except exceptions.ResourceNotFound:
            logging.critical("Unable to get details about volume id -- {0} from openstack".format(volume_id))
    return backup_volumes if backup_volumes else None


def initiate_image_creation():
    """
    This function will kick start the image backup process.
    :return:
    """
    instance_data = fetch_required_vm()
    imaged_servers = []
    snapshot_servers = []
    snapshot_volumes = []
    current_date = datetime.today().strftime(date_format)
    if not instance_data:
        logging.info('No instance metadata matched for backup')
        return None, None
    try:
        for server_id in instance_data:
            try:
                image_name_custom = '{0}_rootfs_{1}_001'.format(instance_data[server_id]['server_name'], current_date)
                snap_desc_custom = '{0}_snapshot_{1}_001'.format(instance_data[server_id]['server_name'], current_date)
                image_snapshot_metadata = {'Image_Created_Date': str(current_date),
                                           'Retention_Count': str(
                                               instance_data[server_id]['metadata']['Retention_Count']),
                                           'Custom_Created_Image': 'Yes', 'Server_ID': server_id}
                volume_snapshot_metadata = {'Snapshot_Created_Date': str(current_date),
                                            'Retention_Count': str(
                                                instance_data[server_id]['metadata']['Retention_Count']),
                                            'Custom_Created_Snapshot': 'Yes', 'Server_ID': server_id}
                if 'Image_Snapshot' in instance_data.get(server_id, {}).get('backup_type', None):
                    logging.info("Creating image snapshot for -- {0}".format(instance_data[server_id]['server_name']))
                    conn.compute.create_server_image(server=server_id, name=image_name_custom,
                                                     metadata=image_snapshot_metadata)
                    imaged_servers.append(server_id)
                if 'Volume_Snapshot' in instance_data.get(server_id, {}).get('backup_type', None):
                    logging.info("Creating volume snapshot for -- {0}".format(instance_data[server_id]['server_name']))
                    try:
                        for disk_id in get_volume_type(instance_data[server_id]['attached_volumes']):
                            snapshot_response = conn.block_storage.create_snapshot(metadata=volume_snapshot_metadata,
                                                                                   force=True, volume_id=disk_id,
                                                                                   name=snap_desc_custom,
                                                                                   description=snap_desc_custom)
                            snapshot_servers.append(snapshot_response.id)
                            snapshot_volumes.append(disk_id)
                    except TypeError:
                        logging.info("Empty volume list for server -- {0}".format(
                            instance_data[server_id]['server_name']))
                if 'Image_Snapshot' not in instance_data.get(server_id, {}).get('backup_type', None) and \
                        'Volume_Snapshot' not in instance_data.get(server_id, {}).get('backup_type', None):
                    logging.warning("No backup has been initiated for server -- {0}".format(
                        instance_data[server_id]['server_name']))
            except (exceptions.HttpException, exceptions.InvalidRequest, exceptions.EndpointNotFound) as e:
                logging.exception(e)
                logging.critical("Error while doing backup of VM. payload -- {0}".format(server_id))
            except KeyError as e:
                logging.exception(e)
                logging.critical("unable to fetch required metadata from server -- {0}".format(
                    instance_data[server_id]['server_name']))
        logging.info('Snapshot id\'s -- {0}'.format(snapshot_servers))
        return imaged_servers, snapshot_volumes
    except Exception as e:
        logging.exception(e)
        exit(1)


def get_backup_images(server_id):
    """
    backup_image_data = {'Server_ID': [{'Image_ID1': images.id1,'Retention_Count': '7'},
    {'Image_ID2': images.id2,'Retention_Count': '7'}],
    'Server_ID': [{'Image_ID1': images.id1,'Retention_Count': '7'}, {'Image_ID2': images.id2,'Retention_Count': '7'}]}
    :param server_id:
    :return:
    """
    try:
        backup_image_data = defaultdict(list)
        for images in conn.compute.images():
            if images.metadata.get('Server_ID', None) in server_id and \
                    images.metadata.get('Custom_Created_Image', None) in ['Yes', 'yes']:
                backup_image_data[images.metadata['Server_ID']].append(
                    {'Image_ID': images.id, 'Retention_Count': images.metadata['Retention_Count'],
                     'Image_Created_Date': images.metadata['Image_Created_Date']})
        return backup_image_data
    except Exception as e:
        logging.exception(e)
        exit(1)


def get_retention_num(image_metadata, backup_flag):
    """
    The method gives the retention count for the given backup images, With the help of this method we can opt for the
    new retention that has been set in instance level.
    it forms a hash map with the given data i.e. {(Created_Date - todays_date) : Retention_number} and it finds the
    minimum key value, Which contains the latest retention number.
    {'ServerID':[{'Image_ID':'12345','Retention_Count':'7','Image_Created_Data':'20190322'},
    {'Image_ID':'67890','Retention_Count':'7','Image_Created_Data':'20190321'}]}
    :param image_metadata:
    :param backup_flag:
    :return:
    """
    current_date = datetime.today().strftime(date_format)
    temp_counter = []
    image_max_retention = {}
    image_created_datediff = {}
    try:
        for server, image_details in image_metadata.iteritems():
            if not temp_counter:
                for meta_tags in image_details:
                    image_created_datediff[diff_between_dates(current_date, meta_tags[backup_flag])] =\
                        int(meta_tags['Retention_Count'])
                image_max_retention[server] = image_created_datediff[min(image_created_datediff)]
                del temp_counter[:]
            else:
                logging.error("Temp_Counter List should be empty, Exiting the script with exit code as 1")
                exit(1)
        return image_max_retention
    except KeyError:
        exit(1)


def diff_between_dates(current_date, snap_date):
    """
    This method will calculate the time difference between the today's date and images created date.
    :param current_date: Today's date
    :param snap_date: image taken date.
    :return: Difference in two date.
    """
    date_now = datetime.strptime(current_date, date_format)
    snapshot_date = datetime.strptime(snap_date, date_format)
    return int((date_now - snapshot_date).days)


def get_oldest_image(server_id):
    """
    This method will find the actually retention of the images, In case if it's changed in future.
    And oldest image will be removed if image count is more than retention count
    :param server_id: Nest dict: Server id , Image id , Image metadata.
    :return:
    """
    current_date = datetime.today().strftime(date_format)
    images_to_be_removed = []
    temp_min_finder = {}
    iter_count = 0
    if not server_id:
        return None
    try:
        bk_image_data = get_backup_images(server_id)
        images_retention = get_retention_num(bk_image_data, 'Image_Created_Date')
        for server, image_details in bk_image_data.iteritems():
            if len(image_details) > int(images_retention[server]):
                for image_id in image_details:
                    temp_min_finder[image_id['Image_ID']] = diff_between_dates(current_date,
                                                                               image_id['Image_Created_Date'])
                    iter_count = len(image_details)
                # Below Loop will help to maintain the actual retention even though multiple runs happened
                # on same days.
                while True:
                    if iter_count > int(images_retention[server]):
                        temp_image_id = max(temp_min_finder, key=temp_min_finder.get)
                        del temp_min_finder[temp_image_id]
                        images_to_be_removed.append(temp_image_id)
                        iter_count -= 1
                    else:
                        break
                temp_min_finder = {}
                iter_count = 0
            else:
                logging.info("Image Count for server - %s is less than retention count", str(server))
        return images_to_be_removed
    except Exception as e:
        logging.exception(e)
        exit(1)


def get_backup_snapshots(volume_id):
    """
    backup_image_data = {'Server_ID': [{'Snapshot_ID1': images.id1,'Retention_Count': '7'},
    {'Snapshot_ID2': images.id2,'Retention_Count': '7'}],
    'Server_ID': [{'Snapshot_ID1': images.id1,'Retention_Count': '7'},
    {'Snapshot_ID2': images.id2,'Retention_Count': '7'}]}
    :param volume_id: List of volumes
    :return:
    """
    try:
        backup_snap_data = defaultdict(list)
        for volume in volume_id:
            try:
                snapshots = list(conn.block_storage.snapshots(volume_id=volume))
                for snap in snapshots:
                    if snap.volume_id in volume_id and \
                            snap.metadata.get('Custom_Created_Snapshot', None) in ['Yes', 'yes']:
                        backup_snap_data[snap.volume_id].append({'Snapshot_ID': snap.id,
                                                                 'Retention_Count': snap.metadata['Retention_Count'],
                                                                 'Snapshot_Created_Date':
                                                                     snap.metadata['Snapshot_Created_Date']})
            except (exceptions.HttpException, exceptions.InvalidRequest, exceptions.EndpointNotFound) as e:
                logging.exception(e)
                logging.critical("Unable to query snapshots for volume id -- {0}".format(volume))
        return backup_snap_data
    except Exception as e:
        logging.exception(e)
        exit(1)


def get_oldest_snapshot(volume_id):
    """
    This method will find the actually retention of the Snapshots, In case if it's changed in future.
    And oldest snapshots will be removed if image count is more than retention count
    :param volume_id: Nest dict: Volume id,Snapshot metadata.
    :return: Snapshots to be removed
    """
    current_date = datetime.today().strftime(date_format)
    snapshots_to_be_removed = []
    temp_min_finder = {}
    iter_count = 0
    if not volume_id:
        return None
    try:
        bk_snap_data = get_backup_snapshots(volume_id)
        snap_retention = get_retention_num(bk_snap_data, 'Snapshot_Created_Date')
        for volume, snap_details in bk_snap_data.iteritems():
            if len(snap_details) > int(snap_retention[volume]):
                for image_id in snap_details:
                    temp_min_finder[image_id['Snapshot_ID']] = diff_between_dates(current_date,
                                                                                  image_id['Snapshot_Created_Date'])
                    iter_count = len(snap_details)
                while True:
                    if iter_count > int(snap_retention[volume]):
                        temp_snap_id = max(temp_min_finder, key=temp_min_finder.get)
                        del temp_min_finder[temp_snap_id]
                        snapshots_to_be_removed.append(temp_snap_id)
                        iter_count -= 1
                    else:
                        break
                temp_min_finder = {}
                iter_count = 0
            else:
                logging.info("Snapshot Count for server - %s is less than retention count", str(volume))
        return snapshots_to_be_removed
    except Exception as e:
        logging.exception(e)
        exit(1)


def remove_old_images(image_list):
    """
    This function will trigger the image deletion for the given id.
    :param image_list: List of images to be deleted
    :return: None
    """
    try:
        for image_id in image_list:
            conn.compute.delete_image(image_id)
            logging.info('Image id - %s has been scheduled for deletion ', image_id)
    except Exception as e:
        logging.exception(e)


def remove_old_snapshots(snapshot_list):
    """
    This func will delete the given snapshot it
    :param snapshot_list: list of snapshot id's
    :return: None
    """
    for snapshot in snapshot_list:
        try:
            conn.block_storage.delete_snapshot(snapshot)
            logging.info("Snapshot id - {0} has been scheduled for deletion".format(snapshot))
        except (exceptions.HttpException, exceptions.InvalidRequest, exceptions.EndpointNotFound) as e:
            logging.exception(e)
            logging.error("Unable to delete snapshot {0}".format(snapshot))
    return None


def main():
    """
    Main function to call the methods required to initiate image creation and deletion of older images.
    :return: None
    """
    global conn
    args = parse_args()
    for profile_name in regions_name_hash:
        logging.info("Currently, Working on {0}".format(profile_name))
        auth = profile_maker(profile_name, args.Username, args.Password)
        try:
            conn = connection.Connection(identity_api_version='3', identity_interface='public',
                                         region_name=regions_name_hash[profile_name], username=auth['username'],
                                         password=auth['password'], project_name=auth['project_name'],
                                         user_domain_name=auth['user_domain_name'], auth_url=auth['auth_url'],
                                         project_id=auth['project_id'])
            server_image_data, server_volume_data = initiate_image_creation()
            if server_image_data or server_volume_data:
                sleep(180)
            if server_image_data:
                images_to_be_deleted = get_oldest_image(server_image_data)
                logging.info("Images acquired for deletion {0}".format(images_to_be_deleted))
                if images_to_be_deleted:
                    logging.info(images_to_be_deleted)
                    remove_old_images(images_to_be_deleted)
                else:
                    logging.info("No images has been scheduled for deletion ")
            if server_volume_data:
                snapshots_to_be_deleted = get_oldest_snapshot(server_volume_data)
                if snapshots_to_be_deleted:
                    logging.info(snapshots_to_be_deleted)
                    remove_old_snapshots(snapshots_to_be_deleted)
                else:
                    logging.info("No snapshot has been scheduled for deletion ")
        except Exception as e:
            logging.exception(e)


if __name__ == '__main__':
    main()
