"""Locate light radio interiors on a pale quiz panel; reject ambiguous layouts."""
from collections import deque

def radio_centers(image):
    rgb=image.convert('RGB')
    scale=min(1,1200/rgb.width)
    if scale<1:rgb=rgb.resize((round(rgb.width*scale),round(rgb.height*scale)))
    w,h=rgb.size
    pixels=rgb.load()
    remaining={(x,y) for y in range(h) for x in range(min(w,round(w*.25)))
               if min(pixels[x,y])>=245 and max(pixels[x,y])-min(pixels[x,y])<=10}
    found=[]
    while remaining:
        seed=remaining.pop();queue=deque([seed]);xs=[];ys=[]
        while queue:
            x,y=queue.popleft();xs.append(x);ys.append(y)
            for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if p in remaining:remaining.remove(p);queue.append(p)
        l,r,t,b=min(xs),max(xs),min(ys),max(ys)
        bw,bh=r-l+1,b-t+1
        if not (7<=bw<=40 and 7<=bh<=40 and .75<=bw/bh<=1.33):continue
        fill=len(xs)/(bw*bh)
        if not .20<=fill<=.90:continue
        # A neutral gray perimeter distinguishes controls from white text/patches.
        border=[]
        for x,y in ((l-1,(t+b)//2),(r+1,(t+b)//2),((l+r)//2,t-1),((l+r)//2,b+1)):
            if 0<=x<w and 0<=y<h:
                nearby=[pixels[xx,yy] for yy in range(max(0,y-2),min(h,y+3)) for xx in range(max(0,x-2),min(w,x+3))]
                border.append(min(nearby,key=lambda p: sum(p)))
        if sum(max(p)-min(p)<35 and min(p)<225 for p in border)<3:continue
        found.append(((l+r)/2,(t+b)/2,bw,bh))
    groups=[]
    for candidate in sorted(found,key=lambda p:p[0]):
        group=next((g for g in groups if abs(g[0][0]-candidate[0])<=4),None)
        if group is None:groups.append([candidate])
        else:group.append(candidate)
    groups=[g for g in groups if 2<=len(g)<=20]
    if len(groups)!=1:raise ValueError('Cannot identify one complete column of radio controls')
    ordered=sorted(groups[0],key=lambda p:p[1])
    if any(b[1]-a[1]<max(a[3],b[3])*1.3 for a,b in zip(ordered,ordered[1:])):
        raise ValueError('Radio controls overlap or are ambiguous')
    return [(round(x/scale),round(y/scale)) for x,y,_,_ in ordered]

def choice_position(image,target,rect):
    index,count=target.get('choice_index'),target.get('choice_count')
    if type(index) is not int or type(count) is not int or not 1<=index<=count<=20:
        raise ValueError('Server did not provide a valid choice index/count')
    centers=radio_centers(image)
    if len(centers)!=count:raise ValueError('Detected control count differs from AI choice count')
    x,y=centers[index-1]
    return (rect[0]+round(x*rect[2]/image.width),rect[1]+round(y*rect[3]/image.height)),(x,y)

