import datetime
from .functions import read_json, aggregate_surveys_no_config
import glob
import json
import logging
import math
import numpy as np
import os
import pandas as pd
import pytz
from typing import List


def convert_time_to_date(submit_time, day, time):
    """
    Takes a single array of timings and a single day
    Args:
        submit_time(datetime):
            date in week for which we want to extract another date and time
        day(int):
            desired day of week
        time(list):
            List of timings times from the configuration surveys information
    """

    # Convert inputted desired day into an integer between 0 and 6
    day = day % 7
    # Get the days of the given week using the dow of the given submit day
    dow = submit_time.weekday()
    days = [submit_time + datetime.timedelta(days=i) for i in range(0 - dow, 7 - dow)]

    time = [str(datetime.timedelta(seconds=t)) for t in time]
    time = [t.split(':') for t in time]
    time = [[int(p) for p in t] for t in time]

    # Get rid of timing
    #     https://stackoverflow.com/questions/26882499/reset-time-part-of-a-pandas-timestamp
    #     print(time)
    days = [d - pd.offsets.Micro(0) for d in days]
    days = [[d.replace(hour=t[0], minute=t[1], second=t[2], microsecond=0) for t in time] for d in days]

    return days[day]


def generate_survey_times(time_start, time_end, timings=[], survey_type='weekly', intervention_dict = None):
    """
    Takes a start time and end time and generates a schedule of all sent surveys in time frame for the given survey type
    Args:
        time_start(str):
            The first date for which we want to generate survey times
        time_end(str):
            The last date for which we want to generate survey times
        timings(list):
            list of survey timings, directly from the configuration file survey information
        survey_type(str):
            What type of survey schedule to generate times for
        intervention_dict(dict):
            A dictionary with keys for each intervention time, each containing a timestamp object
            (only needed for relative surveys)
    Returns:
        surveys(list):
            A list of all survey times that occur between the time_start and time_end per the given survey timings schedule
    """
    if survey_type not in ['weekly', 'absolute', 'relative']:
        raise ValueError('Incorrect type of survey. Ensure this is weekly, absolute, or relative.')

        # Get the number of weeks between start and end time
    t_start = pd.Timestamp(time_start)
    t_end = pd.Timestamp(time_end)
    surveys = []
    
    if survey_type == 'weekly':

        weeks = pd.Timedelta(t_end - t_start).days
        # Get ceiling number of weeks
        weeks = math.ceil(weeks / 7.0)

        # Roll dates
        t_lag = list(np.roll(np.array(timings, dtype="object"), -1))

        # for each week, generate the survey times and append to a list
        start_dates = [time_start + datetime.timedelta(days=7 * (i)) for i in range(weeks)]

        for s in start_dates:
            # Get the starting day of week 
            #         dow_s = s.weekday()
            for i, t in enumerate(t_lag):
                if len(t) > 0:
                    surveys.extend(convert_time_to_date(s, day=i, time=t))
    if survey_type == 'absolute':

        times_df = pd.DataFrame(timings)
        times_df.columns = ['year', 'month', 'day', 'second']
        surveys = pd.to_datetime(times_df).tolist()
        
    if survey_type == 'relative':
        if intervention_dict == None:
            print('Error: No dictionary of interventions provided.')
            return []
        for t in timings: 
            #This could probably be vectorized
            current_time = intervention_dict[t[0]] + pd.Timedelta(t[1], unit='days') + \
            pd.Timedelta(t[2], unit='seconds') 

            surveys.append(current_time)
    return surveys


def gen_survey_schedule(config_path, time_start, time_end, beiwe_ids, all_interventions_dict):
    """
    Args:
        config_path(str):
            File path to study configuration file
        time_start(str):
            The first date of the survey data
        time_end(str):
            The last date of the survey data
        beiwe_ids(list):
            List of users in study for which we are generating a survey schedule
        all_interventions_dict(dict):
            Dictionary containing a key for every beiwe id. 
            Each value in the dict is a dict, with a key for each intervention and a timestamp for each intervention time
            
    Returns:
        times_sur(DataFrame):
            DataFrame with a line for every survey deployed to every user in the study for the given time range
    """
    # List of surveys
    surveys = read_json(config_path)['surveys']
    # For each survey create a list of survey times
    times_sur = []
    for u_id in beiwe_ids:
        print(u_id)
        for i, s in enumerate(surveys):
            s_times = []
            if s['timings']:
                s_times = s_times + generate_survey_times(time_start, time_end, timings=s['timings'], survey_type='weekly')
            if s['absolute_timings']:
                s_times = s_times + generate_survey_times(time_start, time_end, timings=s['absolute_timings'], survey_type='absolute')
            if s['relative_timings']:
                if all_interventions_dict[u_id]: #We can only get relative timings if we have an index time
                    s_times = s_times + generate_survey_times(time_start, time_end, timings=s['relative_timings'], survey_type='relative', intervention_dict = all_interventions_dict[u_id])
                else:
                    print('error: no index time found for user ' + u_id)
            tbl = pd.DataFrame({'delivery_time': s_times})
            tbl['delivery_time'] = pd.to_datetime(tbl['delivery_time']) #May not be necessary, but I'm leaving this in case timestamps are in different formats
            tbl.sort_values('delivery_time', inplace = True)
            tbl.reset_index(drop=True, inplace = True)
            # Create the "next" time column too, which indicates the next time the survey will be deployed
            tbl['next_delivery_time'] = tbl.delivery_time.shift(-1)
            tbl['id'] = i
            tbl['beiwe_id'] = u_id
                    # Get all question IDs for the survey
            qs = [q['question_id'] for q in s['content'] if 'question_id' in q.keys()]
            if len(qs) > 0:
                q_ids = pd.DataFrame({'question_id': qs})
                tbl = pd.merge(tbl, q_ids, how='cross')
            times_sur.append(tbl)

    times_sur = pd.concat(times_sur).reset_index(drop=True)
    return(times_sur)


def survey_submits(study_dir, config_path, time_start, time_end, beiwe_ids, agg, study_tz=None, all_interventions_dict=None):
    """
    Args:
        study_dir(str):
            File path to study data
        config_path(str):
            File path to study configuration file
        time_start(str):
            The first date of the survey data
        time_end(str):
            The last date of the survey data
        beiwe_ids(list):
            List of users in study for which we are generating a survey schedule
        study_tz(str):
            Timezone of study. This defaults to 'America/New_York'
        all_interventions_dict(dict):
            dict containing interventions for each user. Each key in the dict is a beiwe id. Each value is a dict, with a key for each intervention name and a timestamp for each intervention's time

    Returns:
        A DataFrame with all surveys deployed in the given timeframe on the study to the users with completion times
    """
    time_start = pd.Timestamp(time_start)
    time_end = pd.Timestamp(time_end)

    sched = gen_survey_schedule(config_path, time_start, time_end, beiwe_ids, all_interventions_dict)

    # Merge survey submit lines onto the schedule data and identify submitted lines
    submit_lines = pd.merge(
        sched[['delivery_time', 'next_delivery_time', 'id', 'beiwe_id']].drop_duplicates(),
        agg[['Local time', 'config_id', 'survey id', 'beiwe_id']].loc[agg.submit_line == 1].drop_duplicates(),
        how='left',
        left_on=['id', 'beiwe_id'],
        right_on=['config_id', 'beiwe_id'])

    # Get the submitted survey line
    submit_lines['submit_flg'] = np.where(
        (submit_lines['Local time'] >= submit_lines['delivery_time']) &
        (submit_lines['Local time'] < submit_lines['next_delivery_time']),
        1, 0
    )

    # Take the maximum survey submit line
    submit_lines2 = submit_lines.groupby(['delivery_time', 'next_delivery_time', 'survey id', 'beiwe_id', 'config_id'])[
        'submit_flg'].max().reset_index()
    
    for col in ['delivery_time', 'next_delivery_time']:
            submit_lines2[col] = pd.to_datetime(submit_lines2[col])


    # Merge on the times of the survey submission
    merge_cols = ['delivery_time', 'next_delivery_time', 'survey id', 'beiwe_id', 'config_id', 'submit_flg']
    submit_lines3 = pd.merge(submit_lines2, submit_lines[merge_cols + ['Local time']], how='left', left_on=merge_cols,
                             right_on=merge_cols)

    submit_lines3['submit_time'] = np.where(submit_lines3.submit_flg == 1, submit_lines3['Local time'],
                                            np.array(0, dtype='datetime64[ns]'))

    #     # Select appropriate columns
    submit_lines3 = submit_lines3[['survey id', 'delivery_time', 'beiwe_id', 'submit_flg', 'submit_time']]

    submit_lines3['time_to_submit'] = submit_lines3['submit_time'] - submit_lines3['delivery_time']
    
    

    # Create a summary that has survey_id, beiwe_id, num_surveys, num submitted surveys, average time to submit
    summary_cols = ['survey id', 'beiwe_id']
    num_surveys = submit_lines3.groupby(summary_cols)['delivery_time'].nunique()
    num_complete_surveys = submit_lines3.groupby(summary_cols)['submit_flg'].sum()
    avg_time_to_submit = submit_lines3.loc[submit_lines3.submit_flg == 1].groupby(summary_cols)['time_to_submit'].apply(
        lambda x: sum(x, datetime.timedelta()) / len(x))
    #     avg_time_to_submit = submit_lines3.groupby(summary_cols)['time_to_submit'].apply(lambda x: sum(x, datetime.timedelta())/len(x))

    submit_lines_summary = pd.concat([num_surveys, num_complete_surveys, avg_time_to_submit], axis=1).reset_index()
    submit_lines_summary.columns = ['survey id', 'beiwe_id', 'num_surveys', 'num_complete_surveys',
                                    'avg_time_to_submit']
    
    ## make cols more interpretable as "no survey submitted"                              
    submit_lines3['submit_time'] = np.where(submit_lines3['submit_flg'] == 1, submit_lines3['submit_time'] , np.array('NaT', dtype='datetime64[ns]'))
    
    submit_lines3['time_to_submit'] = np.where(submit_lines3['submit_flg'] == 1, submit_lines3['time_to_submit'] , np.array('NaT', dtype='datetime64[ns]'))
    
    
    return submit_lines3.sort_values(['survey id', 'beiwe_id']).drop_duplicates(), submit_lines_summary


def survey_submits_no_config(study_dir, study_tz=None):
    """
    Alternative function for getting the survey completions (doesn't have expected times of surveys)
    Args:
        agg(DataFrame):
            Output of aggregate_surveys_no_config
    """

    tmp = aggregate_surveys_no_config(study_dir, study_tz)

    def summarize_submits(df):
        tmp = {
            'min_time': df.min(),
            'max_time': df.max()
        }
        return pd.Series(tmp, index=['min_time', 'max_time'])

    tmp = tmp.groupby(['survey id', 'beiwe_id', 'surv_inst_flg'])['Local time'].apply(summarize_submits).reset_index()
    tmp = tmp.pivot(index=['survey id', 'beiwe_id', 'surv_inst_flg'], columns='level_3',
                    values='Local time').reset_index()
    tmp['time_to_complete'] = tmp['max_time'] - tmp['min_time']
    tmp['time_to_complete'] = [t.seconds for t in tmp['time_to_complete']]
    return tmp.sort_values(['beiwe_id', 'survey id'])


def get_all_interventions_dict(filepath):
    """
    Placeholder function; should be replaced once we fix the data streams to have timings
    Gets an all_interventions_dict from a table
    Args:
        filepath: the path to a table containing patient information
        Note: right now, the user has to copy the table from the study website into a text processor.
    Returns:
        a dict with one key for each beiwe_id in the study. The value for each key is a dict with a key for each intervention in the study, and a value which is the timestamp 
    filepath(str)
    """
    if filepath is None:
        return({})
    timings_table = pd.read_table(filepath)
    timings_table.drop(['Creation Date', 'Phone registered', 'Phone OS'], axis = 1,  inplace = True)
    timings_table.set_index('Patient ID', inplace = True)
    for col in timings_table.columns:
        timings_table[col] = pd.to_datetime(timings_table[col])
    all_interventions_dict = timings_table.to_dict('index')
    return(all_interventions_dict)
    
    
    

    
    
    
