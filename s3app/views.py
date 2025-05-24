from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.contrib import messages
from .models import Profile

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.db import IntegrityError

import boto3
import uuid

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
    instance.profile.save()

def register_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        confirm = request.POST['confirm']

        if password != confirm:
            messages.error(request, "Passwords do not match.")
            return redirect('register')

        try:
            user = User.objects.create_user(username=username, email=email, password=password)
            messages.success(request, "Registration successful. Please log in.")
            return redirect('login')
        except IntegrityError:
            messages.error(request, "Username already taken.")
            return redirect('register')

    return render(request, 'register.html')

# ========== AUTH VIEWS ==========

def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('profile')
        else:
            messages.error(request, 'Invalid credentials')
    return render(request, 'login.html')


@login_required
def logout_view(request):
    logout(request)
    return redirect('login')


# ========== HELPER FOR S3 ==========

def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        aws_session_token=settings.AWS_SESSION_TOKEN,
        region_name=settings.AWS_S3_REGION_NAME
    )


def generate_presigned_url(key, expiration=300):
    s3 = get_s3_client()
    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': settings.AWS_STORAGE_BUCKET_NAME, 'Key': key},
        ExpiresIn=expiration
    )


# ========== PROFILE VIEW ==========

@login_required
def profile_view(request):
    profile = request.user.profile
    profile_pic_url = None

    if profile.profile_pic_s3_key:
        profile_pic_url = generate_presigned_url(profile.profile_pic_s3_key)

    # print(profile_pic_url)

    return render(request, 'profile.html', {
        'user': request.user,
        'profile_pic_url': profile_pic_url
    })


# ========== UPLOAD PROFILE PICTURE ==========

@login_required
def upload_profile_picture(request):
    if request.method == 'POST' and request.FILES.get('profile_pic'):
        profile = request.user.profile
        file = request.FILES['profile_pic']

        s3 = get_s3_client()

        # Generate unique S3 key
        key = f"users/{request.user.id}/profile_{uuid.uuid4().hex}.jpg"

        # Upload to S3
        s3.upload_fileobj(
            file,
            settings.AWS_STORAGE_BUCKET_NAME,
            key,
            ExtraArgs={'ContentType': file.content_type}
        )

        # Delete previous image if exists
        if profile.profile_pic_s3_key:
            try:
                s3.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=profile.profile_pic_s3_key)
            except Exception as e:
                print("Warning: Couldn't delete old image:", e)

        # Save new key
        profile.profile_pic_s3_key = key
        profile.save()

        messages.success(request, 'Profile picture updated!')
        return redirect('profile')

    return render(request, 'upload_picture.html')


# ========== DELETE PROFILE PICTURE ==========

@login_required
def delete_profile_picture(request):
    profile = request.user.profile
    if profile.profile_pic_s3_key:
        s3 = get_s3_client()
        try:
            s3.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=profile.profile_pic_s3_key)
            profile.profile_pic_s3_key = ''
            profile.save()
            messages.success(request, 'Profile picture deleted.')
        except Exception as e:
            messages.error(request, f'Error deleting image: {str(e)}')
    return redirect('profile')
