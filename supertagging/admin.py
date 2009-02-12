from django.contrib import admin
from django.contrib.contenttypes import generic
from supertagging.models import SuperTag, SuperTaggedItem
from django.contrib.contenttypes.models import ContentType


class SuperTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'stype', 'properties' )
    ordering = ('name', )
    search_fields = ('stype', 'name', )
    list_filter = ('stype', )
    
    
class SuperTaggedItemAdmin(admin.ModelAdmin):
    list_display = ('content_object', 'tag', 'field', 'process_type', 'relevance', 'instances')
    list_filter = ('process_type',)
    
class SuperTaggedRelationItemAdmin(admin.ModelAdmin):
    list_display = ('content_object', 'relation', 'field', 'process_type','instances')  
    list_filter = ('process_type',)
    
    
class SuperTagRelationAdmin(admin.ModelAdmin):
    list_display = ('tag', 'name', 'stype', 'properties')
    ordering = ('tag', )
    search_fields = ('stype', 'name', 'tag')
    list_filter = ('stype', 'name', )
    

