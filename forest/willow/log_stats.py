import os
import sys
import pandas as pd
import numpy as np
import logging
from ..poplar.functions.log import log_to_csv
from ..poplar.legacy.common_funcs import (read_data, write_all_summaries,
                                          datetime2stamp, stamp2datetime)

logger = logging.getLogger(__name__)

def comm_logs_summaries(ID:str, df_text, df_call, stamp_start, stamp_end, tz_str, option):
    """
    Docstring
    Args: Beiwe ID is needed here only for debugging. The other inputs are the outputs from read_comm_logs().
          Option is 'daily' or 'hourly', determining the resolution of the summary stats
          tz_str: timezone where the study was/is conducted
    Return: pandas dataframe of summary stats
    """
    summary_stats = []
    [start_year, start_month, start_day, start_hour, start_min, start_sec] = stamp2datetime(stamp_start,tz_str)
    [end_year, end_month, end_day, end_hour, end_min, end_sec] = stamp2datetime(stamp_end,tz_str)

    ## determine the starting and ending timestamp again based on the option
    if option == 'hourly':
        table_start = datetime2stamp([start_year, start_month, start_day, start_hour,0,0],tz_str)
        table_end = datetime2stamp([end_year, end_month, end_day, end_hour,0,0],tz_str)
        step_size = 3600
    if option == 'daily':
        table_start = datetime2stamp((start_year, start_month, start_day, 0,0,0),tz_str)
        table_end = datetime2stamp((end_year, end_month, end_day,0,0,0),tz_str)
        step_size = 3600*24

    ## for each chunk, calculate the summary statistics (colmean or count)
    for stamp in np.arange(table_start,table_end+1,step=step_size):
        (year, month, day, hour, minute, second) = stamp2datetime(stamp,tz_str)
        if df_text.shape[0] > 0:
            temp_text = df_text[(df_text["timestamp"]/1000>=stamp)&(df_text["timestamp"]/1000<stamp+step_size)]
            m_len = np.array(temp_text['message length'])
            for k in range(len(m_len)):
                if m_len[k]=="MMS":
                    m_len[k]=0
                if isinstance(m_len[k], str)==False:
                    if np.isnan(m_len[k]):
                        m_len[k]=0
            m_len = m_len.astype(int)

            index_s = np.array(temp_text['sent vs received'])=="sent SMS"
            index_r = np.array(temp_text['sent vs received'])=="received SMS"
            send_to_number = np.unique(np.array(temp_text['hashed phone number'])[index_s])
            receive_from_number = np.unique(np.array(temp_text['hashed phone number'])[index_r])
            num_s_tel = len(send_to_number)
            num_r_tel = len(receive_from_number)
            index_mms_s = np.array(temp_text['sent vs received'])=="sent MMS"
            index_mms_r = np.array(temp_text['sent vs received'])=="received MMS"
            num_s = sum(index_s.astype(int))
            num_r = sum(index_r.astype(int))
            num_mms_s = sum(index_mms_s.astype(int))
            num_mms_r = sum(index_mms_r.astype(int))
            total_char_s = sum(m_len[index_s])
            total_char_r = sum(m_len[index_r])
            if option == 'daily':
              received_no_response =  []
              sent_no_response = []
              ## find the phone number in sent_from, but not in send_to
              for tel in receive_from_number:
                if tel not in send_to_number:
                  received_no_response.append(tel)
              for tel in send_to_number:
                if tel not in receive_from_number:
                  sent_no_response.append(tel)
              text_reciprocity_incoming = 0
              text_reciprocity_outgoing = 0
              for tel in received_no_response:
                text_reciprocity_incoming = text_reciprocity_incoming + sum(index_r*(np.array(temp_text['hashed phone number'])==tel))
              for tel in sent_no_response:
                text_reciprocity_outgoing = text_reciprocity_outgoing + sum(index_s*(np.array(temp_text['hashed phone number'])==tel))

        if df_call.shape[0] > 0:
            temp_call = df_call[(df_call["timestamp"]/1000>=stamp)&(df_call["timestamp"]/1000<stamp+step_size)]
            dur_in_sec = np.array(temp_call['duration in seconds'])
            dur_in_sec[np.isnan(dur_in_sec)==True] = 0
            dur_in_min = dur_in_sec/60
            index_in_call = np.array(temp_call['call type'])=="Incoming Call"
            index_out_call = np.array(temp_call['call type'])=="Outgoing Call"
            index_mis_call = np.array(temp_call['call type'])=="Missed Call"
            num_in_call = sum(index_in_call)
            num_out_call = sum(index_out_call)
            num_mis_call = sum(index_mis_call)
            num_uniq_in_call = len(np.unique(np.array(temp_call['hashed phone number'])[index_in_call]))
            num_uniq_out_call = len(np.unique(np.array(temp_call['hashed phone number'])[index_out_call]))
            num_uniq_mis_call = len(np.unique(np.array(temp_call['hashed phone number'])[index_mis_call]))
            total_time_in_call = sum(dur_in_min[index_in_call])
            total_time_out_call = sum(dur_in_min[index_out_call])
        if option == 'daily':
            newline = [year, month, day, num_in_call, num_out_call, num_mis_call, num_uniq_in_call, num_uniq_out_call,
                  num_uniq_mis_call, total_time_in_call, total_time_out_call, num_s, num_r, num_mms_s, num_mms_r, num_s_tel,
                  num_r_tel, total_char_s, total_char_r,text_reciprocity_incoming,text_reciprocity_outgoing]
        if option == 'hourly':
            newline = [year, month, day, hour, num_in_call, num_out_call, num_mis_call, num_uniq_in_call, num_uniq_out_call,
                  num_uniq_mis_call, total_time_in_call, total_time_out_call, num_s, num_r, num_mms_s, num_mms_r, num_s_tel,
                  num_r_tel, total_char_s, total_char_r]
        summary_stats.append(newline)
    summary_stats = np.array(summary_stats)
    if option == 'daily':
        stats_pdframe = pd.DataFrame(summary_stats, columns=['year', 'month', 'day','num_in_call', 'num_out_call', 'num_mis_call',
                'num_in_caller', 'num_out_caller','num_mis_caller', 'total_mins_in_call', 'total_mins_out_call',
                'num_s', 'num_r', 'num_mms_s', 'num_mms_r', 'num_s_tel','num_r_tel', 'total_char_s', 'total_char_r',
                'text_reciprocity_incoming','text_reciprocity_outgoing'])
    if option == 'hourly':
        stats_pdframe = pd.DataFrame(summary_stats, columns=['year', 'month', 'day','hour','num_in_call', 'num_out_call',
                'num_mis_call','num_in_caller', 'num_out_caller','num_mis_caller', 'total_mins_in_call', 'total_mins_out_call',
                'num_s', 'num_r', 'num_mms_s', 'num_mms_r', 'num_s_tel','num_r_tel', 'total_char_s', 'total_char_r'])
    return stats_pdframe

# Main function/wrapper should take standard arguments with Beiwe names:
def log_stats_main(study_folder: str, output_folder:str, tz_str: str,  option: str, time_start = None, time_end = None, beiwe_id = None):
    if os.path.exists(output_folder)==False:
        os.mkdir(output_folder)
    if option == 'both':
        if os.path.exists(output_folder+"/hourly")==False:
            os.mkdir(output_folder+"/hourly")
        if os.path.exists(output_folder+"/daily")==False:
            os.mkdir(output_folder+"/daily")
    log_to_csv(output_folder)
    logger.info("Begin")
    ## beiwe_id should be a list of str
    if beiwe_id == None:
        beiwe_id = os.listdir(study_folder)
    ## create a record of processed user ID and starting/ending time
    record = []
    for ID in beiwe_id:
        sys.stdout.write('User: '+ ID + '\n')
        ## read data
        sys.stdout.write("Read in the csv files ..." + '\n')
        try:
            text_data, text_stamp_start, text_stamp_end = read_data(ID, study_folder, "texts", tz_str, time_start, time_end)
            call_data, call_stamp_start, call_stamp_end = read_data(ID, study_folder, "calls", tz_str, time_start, time_end)
        except Exception as e:
            print("Error in reading data.")
            logging.error()
            raise e
            continue
        ## stamps from call and text should be the stamp_end
        stamp_start = min(text_stamp_start,call_stamp_start)
        stamp_end = max(text_stamp_end, call_stamp_end)
        ## process data

        if option == "both":
            try:
                stats_pdframe1 = comm_logs_summaries(ID, text_data, call_data, stamp_start, stamp_end, tz_str, "hourly")
            except Exception as e:
                print("Error in summarizing hourly statistics.")
                logging.error()
                raise e
                continue

            try:
                stats_pdframe2 = comm_logs_summaries(ID, text_data, call_data, stamp_start, stamp_end, tz_str, "daily")
            except Exception as e:
                print("Error in summarizing daily statistics.")
                logging.error()
                raise e
                continue

            try:
                write_all_summaries(ID, stats_pdframe1, output_folder + "/hourly")
                write_all_summaries(ID, stats_pdframe2, output_folder + "/daily")
            except Exception as e:
                print("Error in writing out summary stats to csv.")
                logging.error()
                raise e
        else:
            try:
                stats_pdframe = comm_logs_summaries(ID, text_data, call_data, stamp_start, stamp_end, tz_str,option)
            except Exception as e:
                print("Error in summarizing statistics.")
                logging.error()
                raise e
                continue
            try:
                write_all_summaries(ID, stats_pdframe, output_folder)
            except Exception as e:
                print("Error in writing out summary stats to csv.")
                logging.error()
                raise e

            try:
                [y1,m1,d1,h1,min1,s1] = stamp2datetime(stamp_start,tz_str)
                [y2,m2,d2,h2,min2,s2] = stamp2datetime(stamp_end,tz_str)
                record.append([str(ID),stamp_start,y1,m1,d1,h1,min1,s1,stamp_end,y2,m2,d2,h2,min2,s2])
            except Exception as e:
                print("Error in appending the record of current subject to history file.")
                logging.error()
                raise e

    logger.info("End")
    ## generate the record file together with logger and comm_logs.csv
    try:
        record = pd.DataFrame(np.array(record), columns=['ID','start_stamp','start_year','start_month','start_day','start_hour','start_min','start_sec','end_stamp','end_year','end_month','end_day','end_hour','end_min','end_sec'])
        record.to_csv(output_folder + "/record.csv",index=False)
        if os.path.exists(output_folder + "/log.csv")==True:
            temp = pd.read_csv(output_folder + "/log.csv")
            if temp.shape[0]==3:
                print("Finished without any warning messages.")
            else:
                print("Finished. Please check log.csv for warning messages.")
    except Exception as e:
        print("Error in writing out record file.")
        logging.error()
        raise e
