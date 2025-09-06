import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import pytz

sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)

users = pd.read_csv('data/users.csv')
attendance = pd.read_csv('data/attendance.csv')

users['is_admin'] = users['is_admin'].astype(str).str.lower().map({
    't': True,
    'f': False
})

users = users[~users['is_admin']]
attendance = attendance[attendance['user_id'].isin(users['user_id'])]

attendance['timestamp'] = pd.to_datetime(attendance['timestamp'])
attendance['timestamp'] = attendance['timestamp'] + timedelta(hours=3)

attendance = attendance[attendance['timestamp'].dt.hour < 22]

merged = pd.merge(attendance, users[['user_id', 'promoter']], on='user_id', how='left')

promoter_attendance = merged.groupby(['promoter', 'ticket_type']).size().unstack(fill_value=0)

print("Attendance by Promoter and Ticket Type:")
print(promoter_attendance)

ticket_counts = attendance['ticket_type'].value_counts()
plt.figure(figsize=(8, 8))
plt.pie(ticket_counts, labels=ticket_counts.index, autopct='%1.1f%%', startangle=90)
plt.title('Proportion of Ticket Types')
plt.show()

hourly_attendance = attendance.set_index('timestamp').resample('H').size()

moving_avg = hourly_attendance.rolling(window=3, center=True).mean()

plt.figure()
moving_avg.plot(label='3-hour Moving Average')
plt.title('Attendance Over Time (3-hour Moving Average)')
plt.xlabel('Time')
plt.ylabel('Number of Attendees')
plt.legend()
plt.show()

attendance['hour'] = attendance['timestamp'].dt.hour
hourly_dist = attendance['hour'].value_counts().sort_index()
plt.figure()
hourly_dist.plot(kind='bar')
plt.title('Attendance by Hour of Day')
plt.xlabel('Hour')
plt.ylabel('Number of Attendees')
plt.xticks(rotation=0)
plt.show()

top_promoters = merged['promoter'].value_counts().head(10)
plt.figure()
top_promoters.plot(kind='barh')
plt.title('Top 10 Promoters by Number of Attendees')
plt.xlabel('Number of Attendees')
plt.ylabel('Promoter')
plt.show()

top_promoter_names = top_promoters.index[:5]
promoter_ticket_dist = merged[merged['promoter'].isin(top_promoter_names)]
promoter_ticket_dist = promoter_ticket_dist.groupby(['promoter', 'ticket_type']).size().unstack()

promoter_ticket_dist.plot(kind='bar', stacked=True)
plt.title('Ticket Type Distribution by Top Promoters')
plt.xlabel('Promoter')
plt.ylabel('Number of Attendees')
plt.legend(title='Ticket Type')
plt.show()