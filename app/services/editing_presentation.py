def host_progress(rows):
    groups={}
    for row in rows:
        key=(row['recipient_id'],row['host_id'])
        group=groups.setdefault(key,{'key':key,'recipient_name':row['recipient_name'],'host_name':row['host_name'],'image_path':row.get('image_path',''),'rows':[]})
        group['rows'].append(row)
    for group in groups.values():
        group['total']=len(group['rows'])
        group['passed']=sum(bool(r['materials_ready']) for r in group['rows'])
        group['waiting']=sum(r['editing_stage']=='WAITING_MATERIAL' for r in group['rows'])
    return [group for group in groups.values() if group['waiting']]
