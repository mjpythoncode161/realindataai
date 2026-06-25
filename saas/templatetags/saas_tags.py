from django import template

from saas.tenant import get_user_organization, user_can_access_feature

register = template.Library()


@register.filter
def has_saas_feature(user, feature_name):
    return user_can_access_feature(user, feature_name)


@register.simple_tag
def org_plan_name(user):
    org = get_user_organization(user)
    if org and org.plan:
        return org.plan.name
    return ""
